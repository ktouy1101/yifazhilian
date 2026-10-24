"""Protocol-level test for the optional stdio MCP client using a fake server."""
import sys

import pytest

from app.services.mcp_client import MCPError, StdioMCPClient

SERVER = r'''
import json, sys
for line in sys.stdin:
    if not line.strip():
        continue
    message = json.loads(line)
    method = message.get("method")
    if method == "initialize":
        print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "serverInfo": {"name": "fake-law", "version": "1"}}}), flush=True)
    elif method == "tools/list":
        print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": {"tools": [
            {"name": "search_statutes"}, {"name": "get_article"},
            {"name": "verify_citation"}]}}), flush=True)
    elif method == "tools/call":
        print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": {
            "content": [{"type": "text", "text": "《民法典》第1219条"}],
            "structuredContent": {"items": [{"text": "说明与同意", "law": "民法典",
                                             "version": "2020-05-28"}]}}}), flush=True)
'''


def test_stdio_client_initializes_lists_and_calls_whitelisted_tool(tmp_path):
    script = tmp_path / "fake_mcp.py"
    script.write_text(SERVER, encoding="utf-8")
    client = StdioMCPClient(sys.executable, (str(script),), timeout=10)
    try:
        assert client.list_tools() == ["get_article", "search_statutes", "verify_citation"]
        result = client.call_tool("search_statutes", {"query": "知情同意", "top_k": 1})
        assert "说明与同意" in result["structuredContent"]["items"][0]["text"]
        with pytest.raises(MCPError):
            client.call_tool("delete_patient_record", {})
    finally:
        client.close()
