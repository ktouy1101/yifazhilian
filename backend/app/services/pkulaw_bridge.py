"""stdio MCP bridge: expose PKU Law's streamable-HTTP tools as a local stdio server.

The backend's MCP client only speaks stdio (see app/services/mcp_client.py), while
PKU Law serves MCP over streamable HTTP with a Bearer token. This bridge is the
adapter: it is spawned as a child process, answers ``tools/list`` / ``tools/call``
on stdin/stdout, and forwards ``search_statutes`` / ``get_article`` to the gateway.

Only the current question text is forwarded. No patient records, identifiers or
conversation history ever leave this process.
"""
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_UPSTREAM = "https://apim-gateway.pkulaw.com/mcp-law-search-service"
TOKEN_ENV = "YIFAZHILIAN_LEGAL_MCP_TOKEN"
UPSTREAM_ENV = "YIFAZHILIAN_LEGAL_MCP_UPSTREAM"
MAX_QUERY_CHARS = 300
MAX_ITEMS = 5

SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "要检索的法律问题或关键词"},
        "top_k": {"type": "integer", "minimum": 1, "maximum": MAX_ITEMS},
    },
    "required": ["query"],
}
ARTICLE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "法规名称"},
        "number": {"type": "string", "description": "条号，例如 1219 或 120.1"},
    },
    "required": ["title", "number"],
}
TOOLS = (
    {"name": "search_statutes", "description": "语义检索北大法宝法规库，返回法条原文与引注信息。",
     "inputSchema": SEARCH_SCHEMA},
    {"name": "get_article", "description": "按法规名称和条号取一条法条原文。",
     "inputSchema": ARTICLE_SCHEMA},
)


class UpstreamError(Exception):
    """Short, token-free failure raised to the parent process."""


def _parse_body(raw, content_type):
    if "event-stream" in (content_type or "") or raw.lstrip().startswith("event:"):
        messages = []
        for line in raw.splitlines():
            if line.startswith("data:"):
                chunk = line[5:].strip()
                if chunk:
                    try:
                        messages.append(json.loads(chunk))
                    except ValueError:
                        continue
        return messages
    try:
        return [json.loads(raw)]
    except ValueError:
        return []


class PkulawUpstream:
    """Minimal streamable-HTTP MCP client for one PKU Law endpoint."""

    def __init__(self, url, token, timeout=20.0):
        self.url = url
        self._token = token
        self.timeout = timeout
        self._session = None
        self._initialized = False
        self._next_id = 1

    def _post(self, payload):
        request = urllib.request.Request(self.url, data=json.dumps(payload).encode("utf-8"),
                                         method="POST")
        request.add_header("Content-Type", "application/json")
        request.add_header("Accept", "application/json, text/event-stream")
        request.add_header("Authorization", "Bearer " + self._token)
        if self._session:
            request.add_header("Mcp-Session-Id", self._session)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                session = response.headers.get("Mcp-Session-Id")
                if session:
                    self._session = session
                return _parse_body(response.read().decode("utf-8", "replace"),
                                   response.headers.get("Content-Type"))
        except urllib.error.HTTPError as error:
            raise UpstreamError(f"法宝网关返回 HTTP {error.code}") from error
        except (urllib.error.URLError, OSError) as error:
            raise UpstreamError("法宝网关不可达") from error

    def _request(self, method, params=None):
        request_id = self._next_id
        self._next_id += 1
        messages = self._post({"jsonrpc": "2.0", "id": request_id, "method": method,
                               "params": params or {}})
        for message in messages:
            if not isinstance(message, dict) or message.get("id") != request_id:
                continue
            if "error" in message:
                raise UpstreamError("法宝网关返回错误")
            result = message.get("result")
            if not isinstance(result, dict):
                raise UpstreamError("法宝网关返回格式无效")
            return result
        raise UpstreamError("法宝网关未返回结果")

    def _initialize(self):
        if self._initialized:
            return
        self._request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                     "clientInfo": {"name": "yifazhilian", "version": "0.9.0"}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self._initialized = True

    def call(self, tool, arguments):
        self._initialize()
        result = self._request("tools/call", {"name": tool, "arguments": arguments})
        if result.get("isError"):
            raise UpstreamError("法宝工具执行失败")
        return result


def _rows(result):
    structured = result.get("structuredContent") or {}
    for key in ("result", "items", "statutes", "results", "data"):
        rows = structured.get(key)
        if isinstance(rows, list):
            return rows
    return []


def _row_text(row):
    """Article body when the gateway returns one, otherwise an explicit descriptor.

    For many queries the service answers with document-level hits (law title,
    number, validity, link) and an empty ``article``. Dropping those made real
    matches look like "nothing found", so they are kept — but the text says out
    loud that no article body came back, otherwise a model would happily quote a
    provision it never read.
    """
    text = str(row.get("article") or row.get("content") or "").strip()
    if text:
        return text
    facts = [f"{label}：{row[key]}" for key, label in
             (("doc_no", "文号"), ("timeliness", "时效"),
              ("issue_department", "制定机关"), ("issue_date", "公布日期"))
             if row.get(key)]
    detail = "；".join(facts)
    return ("法宝只返回了法规条目，未返回条文原文，本条不要引用具体条号。"
            + (f"（{detail}）" if detail else ""))


def to_items(result):
    """Map a PKU Law tool result to the items shape the backend already parses."""
    items = []
    for row in _rows(result):
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        timeliness = str(row.get("timeliness") or "").strip()
        items.append({
            "title": f"{title}（{timeliness}）" if timeliness else title,
            "text": _row_text(row)[:4000],
            "law": title,
            "doc_no": str(row.get("doc_no") or ""),
            "version": str(row.get("issue_date") or ""),
            "url": row.get("url") if isinstance(row.get("url"), str) else None,
            "effective_from": str(row.get("implementation_date") or row.get("issue_date") or ""),
        })
        if len(items) >= MAX_ITEMS:
            break
    return items


def _call_pkulaw(upstream, name, arguments):
    if name == "search_statutes":
        query = str(arguments.get("query") or "")[:MAX_QUERY_CHARS]
        if not query:
            raise UpstreamError("检索词为空")
        try:
            top_k = int(arguments.get("top_k") or 3)
        except (TypeError, ValueError):
            top_k = 3
        result = upstream.call("search_article", {"text": query,
                                                  "size": max(1, min(top_k, MAX_ITEMS))})
        return {"items": to_items(result)}
    if name == "get_article":
        title = str(arguments.get("title") or "").strip()
        number = str(arguments.get("number") or "").strip()
        if not title or not number:
            raise UpstreamError("缺少法规名称或条号")
        result = upstream.call("get_article", {"title": title, "number": number})
        return {"items": to_items(result)}
    raise UpstreamError("工具不在允许范围")


def handle(message, call_tool):
    """Answer one JSON-RPC request; returns None for notifications."""
    method = message.get("method")
    if method is None:
        return None
    request_id = message.get("id")
    params = message.get("params") or {}
    if method == "initialize":
        result = {"protocolVersion": "2024-11-05",
                  "capabilities": {"tools": {"listChanged": False}},
                  "serverInfo": {"name": "pkulaw-bridge", "version": "0.1.0"}}
    elif method == "tools/list":
        result = {"tools": list(TOOLS)}
    elif method == "tools/call":
        name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}
        payload = call_tool(name, arguments)
        result = {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
                  "structuredContent": payload, "isError": False}
    elif method in ("notifications/initialized", "notifications/cancelled"):
        return None
    else:
        return {"jsonrpc": "2.0", "id": request_id,
                "error": {"code": -32601, "message": "不支持的方法"}}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def serve(stream_in=None, stream_out=None):
    stream_in = stream_in or sys.stdin
    stream_out = stream_out or sys.stdout
    token = os.environ.get(TOKEN_ENV, "").strip()
    upstream_url = os.environ.get(UPSTREAM_ENV, "").strip() or DEFAULT_UPSTREAM
    upstream = PkulawUpstream(upstream_url, token) if token else None

    def call_tool(name, arguments):
        if upstream is None:
            raise UpstreamError("未配置法宝 Token")
        return _call_pkulaw(upstream, name, arguments)

    for line in stream_in:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except ValueError:
            continue
        try:
            response = handle(message, call_tool)
        except UpstreamError as error:
            response = {"jsonrpc": "2.0", "id": message.get("id"),
                        "error": {"code": -32000, "message": str(error)}}
        if response is None:
            continue
        stream_out.write(json.dumps(response, ensure_ascii=False) + "\n")
        stream_out.flush()


if __name__ == "__main__":
    serve()
