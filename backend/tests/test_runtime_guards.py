"""Runtime guards: reported mode, demo-login flag and API-key-free logging."""
import app.config as config

from app.ai.providers.mock import MockProvider
from app.api.routes import health


def _values(monkeypatch, values):
    monkeypatch.setattr(config, "_read_kv", lambda env_file, environ: dict(values))


def test_mode_defaults_to_demo(monkeypatch):
    _values(monkeypatch, {})
    assert config.runtime_mode() == "demo"


def test_mode_reads_production(monkeypatch):
    _values(monkeypatch, {"YIFAZHILIAN_RUNTIME_MODE": " Production "})
    assert config.runtime_mode() == "production"


def test_unknown_mode_never_claims_production(monkeypatch):
    _values(monkeypatch, {"YIFAZHILIAN_RUNTIME_MODE": "prod"})
    assert config.runtime_mode() == "demo"


def test_legal_fallback_is_opt_in(monkeypatch):
    _values(monkeypatch, {})
    assert config.legal_mcp_fallback_enabled() is False
    _values(monkeypatch, {"YIFAZHILIAN_LEGAL_MCP_FALLBACK": "1"})
    assert config.legal_mcp_fallback_enabled() is True


def test_demo_auth_honours_env_file(monkeypatch):
    _values(monkeypatch, {})
    assert config.demo_auth_enabled() is True
    _values(monkeypatch, {"YIFAZHILIAN_DEMO_AUTH": "0"})
    assert config.demo_auth_enabled() is False


def test_public_health_exposes_nothing_operational():
    """公开接口只说活着和数据在哪；模型/模式/演示开关不能挂在这里。"""
    from types import SimpleNamespace
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(database=None)))
    payload = health(request)
    assert payload == {"status": "ok", "storage": "sqlite_local"}
    for leaked in ("mode", "demo_auth", "ai_provider", "external_network", "legal_retrieval"):
        assert leaked not in payload


def test_admin_numbers_join_file_and_env(monkeypatch):
    """管理员名单：项目内文件 + 环境变量，取并集。"""
    monkeypatch.setattr(config, "_admin_file_numbers", lambda: {"19000000000"})
    monkeypatch.setattr(config, "_read_kv", lambda env_file, environ: {
        "YIFAZHILIAN_ADMIN_PHONE": "13900000001, 13900000002"})
    assert config.admin_phones() == frozenset({"19000000000", "13900000001", "13900000002"})


def test_admin_file_ignores_comments_and_blanks(monkeypatch, tmp_path):
    path = tmp_path / "admins.txt"
    path.write_text("# 注释\n\n19000000001\n19000000002  # 尾注\n", encoding="utf-8")
    monkeypatch.setattr(config, "ADMIN_FILE", path)
    assert config._admin_file_numbers() == {"19000000001", "19000000002"}


def test_allowed_hosts_env_extends_defaults(monkeypatch):
    """部署到域名后，TrustedHost 必须认识它，否则所有请求都会 400。"""
    monkeypatch.setattr(config, "_read_kv", lambda env_file, environ: {
        "YIFAZHILIAN_ALLOWED_HOSTS": "api.example.com, example.org;api.example.com"})
    hosts = config.allowed_hosts()
    assert "api.example.com" in hosts and "example.org" in hosts
    assert hosts.count("api.example.com") == 1
    assert "localhost" in hosts


def test_allowed_hosts_defaults_without_env(monkeypatch):
    monkeypatch.setattr(config, "_read_kv", lambda env_file, environ: {})
    assert config.allowed_hosts() == ["127.0.0.1", "localhost", "testserver", "192.168.199.126"]
