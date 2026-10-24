"""Test isolation.

The suite must not inherit whatever the developer has in backend/.env: with a
real legal MCP configured, retrieval-based assertions would flip from the local
corpus to external results and pass or fail by machine. Tests that exercise MCP
pass MCPSettings()/environ explicitly instead.
"""
import os

os.environ["YIFAZHILIAN_LEGAL_MCP_COMMAND"] = ""
os.environ["YIFAZHILIAN_DEMO_AUTH"] = "1"
