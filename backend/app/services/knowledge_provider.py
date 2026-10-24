"""Knowledge provider boundary: SQLite by default, optional legal MCP.

MCP is legal-domain only, read-only and fails closed. It never receives patient
records, vitals, document text, tokens or conversation history.
"""
from hashlib import sha256
import threading

from app.ai.providers.base import KnowledgeChunk
from app.config import MCPSettings
from app.services.knowledge import retrieve as retrieve_local
from app.services.mcp_client import MCPError, StdioMCPClient


class KnowledgeProviderError(Exception):
    """Safe failure; callers may show a generic temporary-unavailable message."""


class LocalKnowledgeProvider:
    def uses_database(self, domain):
        return True

    def mode(self, domain):
        return "sqlite_keyword_v1"

    def search(self, connection, domain, text, limit=2):
        return retrieve_local(connection, domain, text, limit=limit)

    def close(self):
        pass


def _explain_mcp_result(result, limit):
    structured = result.get("structuredContent")
    items = None
    if isinstance(structured, list):
        items = structured
    elif isinstance(structured, dict):
        for key in ("items", "statutes", "results", "data"):
            if isinstance(structured.get(key), list):
                items = structured[key]
                break
    if items is None:
        parts = result.get("content") or []
        texts = [str(part.get("text", "")) for part in parts
                 if isinstance(part, dict) and part.get("type") == "text"]
        text = "\n".join(part for part in texts if part).strip()
        items = [{"text": text, "title": "china-law-mcp 检索结果"}] if text else []
    chunks = []
    for item in items[:limit]:
        if isinstance(item, str):
            item = {"text": item}
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or item.get("content") or item.get("snippet") or "").strip()
        if not text:
            continue
        title = str(item.get("title") or item.get("law") or "china-law-mcp 检索结果")[:200]
        digest = sha256((title + "\n" + text).encode("utf-8")).hexdigest()[:16]
        url = item.get("url")
        chunks.append(KnowledgeChunk(
            "mcp-law-" + digest, "legal", title, text[:4000],
            url if isinstance(url, str) else None, (),
            source_id="mcp:china-law", source_title="china-law-mcp（外部只读）",
            version=str(item.get("version") or "external")[:80], status="external",
            effective_from=item.get("effective_from"), effective_until=item.get("effective_until"),
            reviewed_by=None))
    return chunks


class MCPLegalKnowledgeProvider:
    def __init__(self, client, local=None):
        self._client = client
        self._local = local or LocalKnowledgeProvider()
        self._lock = threading.Lock()

    def uses_database(self, domain):
        # Legal MCP must not run inside a SQLite transaction; medical stays local.
        return domain != "legal"

    def mode(self, domain):
        return "legal_mcp_v1" if domain == "legal" else "sqlite_keyword_v1"

    def search(self, connection, domain, text, limit=2):
        if domain != "legal":
            return self._local.search(connection, domain, text, limit=limit)
        try:
            with self._lock:
                result = self._client.call_tool(
                    "search_statutes", {"query": text[:300], "top_k": max(1, min(limit, 5))})
        except MCPError as error:
            raise KnowledgeProviderError("法律知识检索暂不可用；未使用旧资料替代。") from error
        return _explain_mcp_result(result, limit)

    def close(self):
        with self._lock:
            self._client.close()


def create_knowledge_provider(settings: MCPSettings | None = None):
    local = LocalKnowledgeProvider()
    if settings is None or not settings.enabled:
        return local
    client = StdioMCPClient(settings.command, settings.args, timeout=settings.timeout,
                            cwd=settings.cwd, env=settings.env)
    return MCPLegalKnowledgeProvider(client, local)
