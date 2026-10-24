"""Optional legal MCP provider: domain isolation, citations and fail-closed."""
from pathlib import Path
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import AISettings, MCPSettings
from app.db import Database, DEFAULT_DB_PATH
from app.main import create_app
from app.services.knowledge_provider import (KnowledgeProviderError, LocalKnowledgeProvider,
                                             MCPLegalKnowledgeProvider, create_knowledge_provider)
from app.services.mcp_client import MCPError


class FakeClient:
    def __init__(self, result=None, error=None):
        self.result = result or {"content": [{"type": "text", "text": "《民法典》第1219条：说明与同意。"}]}
        self.error = error
        self.calls = []
        self.closed = False

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if self.error:
            raise self.error
        return self.result

    def close(self):
        self.closed = True


@pytest.fixture
def database(tmp_path, monkeypatch):
    connect = sqlite3.connect

    def isolated(path, *args, **kwargs):
        assert Path(path).resolve() != DEFAULT_DB_PATH.resolve()
        return connect(path, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", isolated)
    return Database(tmp_path / "provider.sqlite3")


def test_mcp_is_legal_only_and_returns_external_citation(database):
    client = FakeClient()
    provider = MCPLegalKnowledgeProvider(client)
    with database.transaction() as connection:
        legal = provider.search(connection, "legal", "知情同意", limit=2)
        medical = provider.search(connection, "medical", "用药", limit=2)
    assert client.calls == [("search_statutes", {"query": "知情同意", "top_k": 2})]
    assert legal and legal[0].domain == "legal" and legal[0].status == "external"
    assert legal[0].source_id == "mcp:china-law"
    assert "1219" in legal[0].text
    assert medical and medical[0].domain == "medical"
    assert provider.mode("legal") == "legal_mcp_v1"
    assert provider.mode("medical") == "sqlite_keyword_v1"


def test_mcp_structured_items_are_normalized(database):
    client = FakeClient({"structuredContent": {"items": [
        {"id": "a", "law": "民法典", "article": "1219", "text": "说明义务与明确同意。", "version": "2020-05-28"},
        {"id": "b", "law": "个人信息保护法", "article": "15", "text": "便捷撤回同意。", "url": "https://example.invalid/law"},
    ]}})
    provider = MCPLegalKnowledgeProvider(client)
    with database.transaction() as connection:
        items = provider.search(connection, "legal", "同意", limit=2)
    assert len(items) == 2 and items[0].title == "民法典"
    assert items[0].version == "2020-05-28"
    assert items[1].url == "https://example.invalid/law"


def test_mcp_failure_is_not_silently_replaced_by_local_data(database):
    provider = MCPLegalKnowledgeProvider(FakeClient(error=MCPError("测试 MCP 不可用")))
    with database.transaction() as connection:
        with pytest.raises(KnowledgeProviderError):
            provider.search(connection, "legal", "知情同意")


def test_provider_factory_is_local_by_default_and_mcp_when_configured():
    local = create_knowledge_provider(MCPSettings())
    assert isinstance(local, LocalKnowledgeProvider)
    configured = create_knowledge_provider(MCPSettings(command="uvx", args=("china-law-mcp",)))
    assert isinstance(configured, MCPLegalKnowledgeProvider)
    configured.close()


def test_route_returns_503_instead_of_local_answer_when_mcp_fails(database):
    class BrokenProvider:
        def uses_database(self, domain):
            return domain != "legal"

        def mode(self, domain):
            return "legal_mcp_v1"

        def search(self, connection, domain, text, limit=2):
            raise KnowledgeProviderError("法律知识检索暂不可用；未使用旧资料替代。")

        def close(self):
            pass

    app = create_app(database, ai_settings=AISettings(), mcp_settings=MCPSettings())
    with TestClient(app) as client:
        app.state.knowledge_provider = BrokenProvider()
        login = client.post("/api/v1/auth/demo-login", json={"demo_alias": "demo-patient-001"})
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        client.post("/api/v1/consents", headers=headers, json={"scope": "ai_legal"})
        cid = client.post("/api/v1/conversations", headers=headers, json={"domain": "legal"}).json()["id"]
        # A general legal question must still use the external/MCP provider;
        # consent/records/privacy questions are handled by the local legal guide.
        response = client.post(f"/api/v1/conversations/{cid}/messages", headers=headers,
                               json={"text": "医院感染管理有哪些法律规定"})
        assert response.status_code == 503
        assert "暂不可用" in response.json()["detail"]
        with database.transaction() as connection:
            assert connection.execute("SELECT count(*) FROM messages WHERE conversation_id=?", (cid,)).fetchone()[0] == 0
