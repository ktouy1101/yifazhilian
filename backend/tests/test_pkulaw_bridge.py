"""Bridge between the local stdio MCP client and PKU Law's HTTP gateway."""
import json

import pytest

from pathlib import Path

from app.config import read_mcp_settings
from app.services import pkulaw_bridge

# Shape observed from mcp-law-search-service / search_article (trimmed).
UPSTREAM_RESULT = {
    "content": [{"type": "text", "text": "[]"}],
    "structuredContent": {"result": [
        {"gid": "aa00daaeb5a4fe4ebdfb", "title": "中华人民共和国民法典",
         "article": "第一千二百一十九条　医务人员在诊疗活动中应当向患者说明病情和医疗措施。",
         "doc_no": "中华人民共和国主席令第45号", "timeliness": "现行有效",
         "effectiveness": "法律", "issue_department": "全国人民代表大会",
         "issue_date": "2020-05-28", "implementation_date": "2021-01-01",
         "lib": "chl", "url": "https://pkulaw.com/chl/aa00daaeb5a4fe4ebdfb.html"},
        {"gid": "66384ef45f434b94bdfb", "title": "卫生部医政司关于推荐使用《医疗知情同意书》的函(一)",
         "article": "", "doc_no": "卫医政疗便函〔2010〕42号", "timeliness": "现行有效",
         "issue_date": "2010-03-04", "url": "https://pkulaw.com/chl/66384ef45f434b94bdfb.html"},
    ]},
    "isError": False,
}


class StubUpstream:
    def __init__(self, result=None, error=None):
        self.result = result or UPSTREAM_RESULT
        self.error = error
        self.calls = []

    def call(self, tool, arguments):
        self.calls.append((tool, arguments))
        if self.error:
            raise self.error
        return self.result


def test_env_file_values_reach_the_bridge_without_process_env():
    settings = read_mcp_settings(
        Path("__no_such_env_file__"),
        {"YIFAZHILIAN_LEGAL_MCP_COMMAND": "python",
         "YIFAZHILIAN_LEGAL_MCP_ARGS": "-m app.services.pkulaw_bridge",
         "YIFAZHILIAN_LEGAL_MCP_TOKEN": "unit-test-token",
         "YIFAZHILIAN_LEGAL_MCP_UPSTREAM": "https://example.invalid/mcp"})
    assert settings.command == "python"
    assert settings.args == ("-m", "app.services.pkulaw_bridge")
    assert settings.env == {"YIFAZHILIAN_LEGAL_MCP_TOKEN": "unit-test-token",
                            "YIFAZHILIAN_LEGAL_MCP_UPSTREAM": "https://example.invalid/mcp"}


def test_items_map_to_the_shape_the_backend_parses():
    items = pkulaw_bridge.to_items(UPSTREAM_RESULT)
    assert len(items) == 2  # document-only hit is kept, with an explicit warning
    item = items[0]
    assert item["text"].startswith("第一千二百一十九条")
    assert item["title"] == "中华人民共和国民法典（现行有效）"
    assert item["version"] == "2020-05-28"
    assert item["effective_from"] == "2021-01-01"
    assert item["url"].endswith("aa00daaeb5a4fe4ebdfb.html")
    assert "未返回条文原文" in items[1]["text"]
    assert "卫医政疗便函〔2010〕42号" in items[1]["text"]


def test_document_level_hits_are_never_dropped():
    result = {"structuredContent": {"result": [
        {"title": "医疗事故处理条例", "article": "", "doc_no": "国务院令第351号",
         "timeliness": "现行有效", "url": "https://pkulaw.com/chl/x.html"},
    ]}}
    items = pkulaw_bridge.to_items(result)
    assert len(items) == 1
    assert items[0]["title"] == "医疗事故处理条例（现行有效）"
    assert "不要引用具体条号" in items[0]["text"]
    assert "国务院令第351号" in items[0]["text"]


def test_search_statutes_is_forwarded_as_search_article():
    upstream = StubUpstream()
    payload = pkulaw_bridge._call_pkulaw(upstream, "search_statutes",
                                         {"query": "知情同意", "top_k": 2})
    assert upstream.calls == [("search_article", {"text": "知情同意", "size": 2})]
    assert len(payload["items"]) == 2


def test_top_k_is_clamped_and_query_truncated():
    upstream = StubUpstream()
    pkulaw_bridge._call_pkulaw(upstream, "search_statutes",
                               {"query": "长" * 500, "top_k": 99})
    tool, arguments = upstream.calls[0]
    assert tool == "search_article"
    assert arguments["size"] == pkulaw_bridge.MAX_ITEMS
    assert len(arguments["text"]) == pkulaw_bridge.MAX_QUERY_CHARS


def test_unknown_tool_is_refused():
    with pytest.raises(pkulaw_bridge.UpstreamError):
        pkulaw_bridge._call_pkulaw(StubUpstream(), "delete_patient_record", {})


def test_initialize_and_tools_list_are_served():
    init = pkulaw_bridge.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"}, None)
    assert init["result"]["serverInfo"]["name"] == "pkulaw-bridge"
    listed = pkulaw_bridge.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, None)
    names = {tool["name"] for tool in listed["result"]["tools"]}
    assert names == {"search_statutes", "get_article"}


def test_notifications_produce_no_response():
    assert pkulaw_bridge.handle(
        {"jsonrpc": "2.0", "method": "notifications/initialized"}, None) is None


def test_served_call_returns_structured_items():
    def call_tool(name, arguments):
        assert name == "search_statutes"
        return {"items": pkulaw_bridge.to_items(UPSTREAM_RESULT)}

    response = pkulaw_bridge.handle(
        {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
         "params": {"name": "search_statutes", "arguments": {"query": "知情同意"}}}, call_tool)
    result = response["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["items"][0]["law"] == "中华人民共和国民法典"
    assert json.loads(result["content"][0]["text"])["items"]


def test_upstream_failure_is_reported_as_an_error_not_as_empty_success():
    with pytest.raises(pkulaw_bridge.UpstreamError):
        pkulaw_bridge._call_pkulaw(StubUpstream(error=pkulaw_bridge.UpstreamError("网关超时")),
                                   "search_statutes", {"query": "知情同意"})
