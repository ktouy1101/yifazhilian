"""Minimal MCP stdio client for one optional, read-only legal knowledge tool.

No MCP SDK dependency. Only newline-delimited JSON-RPC is used; the client
never sends patient records, chat history or identifiers to the MCP process.
"""
import json
import os
import queue
import subprocess
import threading
import time

ALLOWED_TOOLS = frozenset({"search_statutes", "get_article", "verify_citation"})
MAX_MESSAGE_BYTES = 256 * 1024
ENV_ALLOWLIST = (
    "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE",
    "LOCALAPPDATA", "APPDATA", "PYTHONUTF8", "PYTHONIOENCODING", "PYTHONPATH",
    # Only what a bridge needs to reach its own upstream; nothing patient-related.
    "YIFAZHILIAN_LEGAL_MCP_TOKEN", "YIFAZHILIAN_LEGAL_MCP_UPSTREAM",
)


class MCPError(Exception):
    """Safe, short error; never includes raw server output or query text."""


class StdioMCPClient:
    def __init__(self, command: str, args: tuple[str, ...] = (), *, timeout: float = 20.0,
                 cwd: str = "", env: dict | None = None):
        self.command = command
        self.args = tuple(args)
        self.timeout = timeout
        self.cwd = cwd
        self._env = dict(env or {})
        self._lock = threading.RLock()
        self._process = None
        self._lines = queue.Queue()
        self._stderr = []
        self._next_id = 1
        self._initialized = False
        self._tools = frozenset()

    @property
    def diagnostic(self) -> str:
        return "\n".join(self._stderr[-5:])[-1000:]

    def _environment(self):
        result = {key: os.environ[key] for key in ENV_ALLOWLIST if key in os.environ}
        result.update({key: str(value) for key, value in self._env.items()})
        result.setdefault("PYTHONUTF8", "1")
        return result

    def _start_locked(self):
        if self._process is not None and self._process.poll() is None:
            return
        if not self.command:
            raise MCPError("法律知识 MCP 未配置")
        try:
            self._process = subprocess.Popen(
                [self.command, *self.args], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                bufsize=1, cwd=self.cwd or None, env=self._environment(),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except (OSError, ValueError) as error:
            raise MCPError("法律知识 MCP 无法启动") from error
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stdout(self):
        try:
            for line in self._process.stdout:
                if len(line.encode("utf-8", "replace")) > MAX_MESSAGE_BYTES:
                    self._lines.put(MCPError("法律知识 MCP 返回内容过大"))
                    return
                self._lines.put(line)
        except (OSError, ValueError):
            pass
        self._lines.put(None)

    def _read_stderr(self):
        try:
            for line in self._process.stderr:
                self._stderr.append(line.rstrip())
                if len(self._stderr) > 20:
                    self._stderr.pop(0)
        except (OSError, ValueError):
            pass

    def _send_locked(self, payload):
        if self._process is None or self._process.poll() is not None:
            raise MCPError("法律知识 MCP 已退出")
        try:
            self._process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self._process.stdin.flush()
        except (OSError, ValueError) as error:
            raise MCPError("法律知识 MCP 写入失败") from error

    def _request_locked(self, method, params=None):
        request_id = self._next_id
        self._next_id += 1
        self._send_locked({"jsonrpc": "2.0", "id": request_id, "method": method,
                           "params": params or {}})
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MCPError("法律知识 MCP 响应超时")
            try:
                line = self._lines.get(timeout=remaining)
            except queue.Empty:
                raise MCPError("法律知识 MCP 响应超时") from None
            if line is None:
                raise MCPError("法律知识 MCP 已退出")
            if isinstance(line, MCPError):
                raise line
            try:
                message = json.loads(line)
            except (TypeError, ValueError):
                continue
            if not isinstance(message, dict) or message.get("id") != request_id:
                continue
            if "error" in message:
                raise MCPError("法律知识 MCP 返回错误")
            result = message.get("result")
            if not isinstance(result, dict):
                raise MCPError("法律知识 MCP 返回格式无效")
            return result

    def _initialize_locked(self):
        if self._initialized:
            return
        self._start_locked()
        self._request_locked("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "yifazhilian", "version": "0.9.0"},
        })
        self._send_locked({"jsonrpc": "2.0", "method": "notifications/initialized"})
        result = self._request_locked("tools/list")
        tools = result.get("tools") or []
        self._tools = frozenset(item.get("name") for item in tools if isinstance(item, dict))
        if "search_statutes" not in self._tools:
            raise MCPError("法律知识 MCP 缺少 search_statutes 工具")
        self._initialized = True

    def list_tools(self):
        with self._lock:
            self._initialize_locked()
            return sorted(self._tools)

    def call_tool(self, name: str, arguments: dict):
        # Tool whitelist is enforced here, not only by prompt instructions.
        if name not in ALLOWED_TOOLS:
            raise MCPError("法律知识 MCP 工具不在白名单")
        if not isinstance(arguments, dict):
            raise MCPError("法律知识 MCP 参数无效")
        with self._lock:
            self._initialize_locked()
            if name not in self._tools:
                raise MCPError("法律知识 MCP 没有请求的工具")
            result = self._request_locked("tools/call", {"name": name, "arguments": arguments})
            if result.get("isError"):
                raise MCPError("法律知识 MCP 工具执行失败")
            return result

    def close(self):
        with self._lock:
            process = self._process
            self._process = None
            self._initialized = False
            if process is None:
                return
            try:
                if process.stdin:
                    process.stdin.close()
            except OSError:
                pass
            try:
                process.terminate()
                process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                except OSError:
                    pass
