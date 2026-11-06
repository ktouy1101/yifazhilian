"""Configuration. Demo mode remains the default; WeChat login activates when
YIFAZHILIAN_WECHAT_APPID and YIFAZHILIAN_WECHAT_SECRET are both set."""
import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

API_PREFIX = "/api/v1"
TOKEN_TTL_SECONDS = 30 * 24 * 3600
CONSENT_TTL_SECONDS = 30 * 24 * 3600
LOCAL_CONSENT_TTL_SECONDS = 30 * 24 * 3600


def consent_ttl(scope: str) -> int:
    """Consent is remembered per purpose for 30 days; revoke or a new notice
    version is what asks again, not every visit."""
    return LOCAL_CONSENT_TTL_SECONDS if scope in ("vitals", "records_read") else CONSENT_TTL_SECONDS


def demo_auth_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Whether the local demo login (fixed code 123456, echoed as dev_code) is on.

    Defaults to on so developer tools and the M11 HTTP acceptance tests keep
    working out of the box. Set YIFAZHILIAN_DEMO_AUTH=0 for any environment real
    users can reach: /auth/send-code then issues a random 6-digit code and never
    returns it in the response. Note that turning this off requires a real SMS
    channel, otherwise nobody can log in.
    """
    values = _read_kv(None, environ)
    return values.get("YIFAZHILIAN_DEMO_AUTH", "1").strip().lower() not in ("0", "false", "no", "off")


def runtime_mode(environ: Mapping[str, str] | None = None) -> str:
    """Reported by /health. Never derive this from a constant: the demo baseline
    must not claim to be production."""
    mode = (_read_kv(None, environ).get("YIFAZHILIAN_RUNTIME_MODE", "demo") or "").strip().lower()
    return mode if mode in ("demo", "production") else "demo"


ADMIN_FILE = Path(__file__).resolve().parents[1] / "admins.txt"


def _admin_file_numbers() -> set[str]:
    """管理员名单文件：一行一个手机号，# 开头为注释。

    放在仓库里是有意的——它不是密钥，而是“谁可以当审核员”的显式决定，
    改动需要经过代码评审；环境变量仍然可以追加，两者取并集。
    """
    if not ADMIN_FILE.is_file():
        return set()
    numbers = set()
    for line in ADMIN_FILE.read_text(encoding="utf-8-sig").splitlines():
        entry = line.split("#", 1)[0].strip()
        if entry:
            numbers.add(entry)
    return numbers


def admin_phones(environ: Mapping[str, str] | None = None) -> frozenset[str]:
    """Phone numbers granted the reviewer role on login.

    Admins are provisioned by configuration, never by self-service: the account
    that can approve volunteers and publish routes must be a deliberate choice.
    """
    raw = (_read_kv(None, environ).get("YIFAZHILIAN_ADMIN_PHONE", "") or "").strip()
    parts = raw.replace(";", ",").split(",")
    from_env = {part.strip() for part in parts if part.strip()}
    return frozenset(from_env | _admin_file_numbers())


def legal_mcp_fallback_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Opt-in: when the legal MCP is down, answer from the local corpus instead of 503.

    Off by default, because the local legal corpus is a small demo excerpt and a
    silent substitution could look authoritative.
    """
    values = _read_kv(None, environ)
    return values.get("YIFAZHILIAN_LEGAL_MCP_FALLBACK", "0").strip().lower() in ("1", "true", "yes", "on")


# 云托管/云开发运行时会注入这些变量之一；此时 Host 头是内部域名，
# 无法预先枚举，直接放行（鉴权仍由令牌保证）。
CLOUD_RUNTIME_ENV_MARKERS = (
    "K_SERVICE", "TCB_ENV", "WX_CLOUD_ENV", "CLOUDRUN_ENV",
    "SCF_FUNCTIONNAME", "TCB_CONTEXT_NAMESPACE",
)


def in_cloud_runtime(environ: Mapping[str, str] | None = None) -> bool:
    source = environ if environ is not None else os.environ
    return any(str(source.get(name) or "").strip() for name in CLOUD_RUNTIME_ENV_MARKERS)


def allowed_hosts(environ: Mapping[str, str] | None = None) -> list[str]:
    """Hosts accepted by TrustedHostMiddleware.

    Local development addresses stay allowed; deploying behind a domain needs
    YIFAZHILIAN_ALLOWED_HOSTS=example.com so requests are not rejected with 400.
    在云托管里运行时（callContainer 的 Host 是内部域名）直接放行全部。
    """
    if in_cloud_runtime(environ):
        return ["*"]
    base = ["127.0.0.1", "localhost", "testserver", "192.168.199.126"]
    raw = (_read_kv(None, environ).get("YIFAZHILIAN_ALLOWED_HOSTS", "") or "").strip()
    extra: list[str] = []
    for item in raw.replace(";", ",").split(","):
        name = item.strip()
        if name and name not in base and name not in extra:
            extra.append(name)
    return base + extra


DISCLAIMER = "仅合成数据演示；非真实诊疗或法律意见；紧急情况请直接联系病区医护。"
DISCLAIMER_LEGAL = "仅合成数据演示；不构成正式法律意见；复杂争议请咨询律师或拨打12348。"


@dataclass(frozen=True)
class WechatConfig:
    appid: str = ""
    secret: str = ""

    @property
    def enabled(self) -> bool:
        return bool(self.appid and self.secret)


@dataclass(frozen=True)
class MCPSettings:
    command: str = ""
    args: tuple[str, ...] = ()
    timeout: float = 20.0
    cwd: str = ""
    # Values from the .env file never reach os.environ, so they are forwarded to
    # the bridge explicitly instead of relying on inheritance.
    env: dict = field(default_factory=dict)

    @property
    def enabled(self) -> bool:
        return bool(self.command)


@dataclass(frozen=True)
class AISettings:
    provider: str = "mock"
    base_url: str = ""
    model: str = ""
    api_key: str = field(default="", repr=False)
    display_name: str = "本地演示"


def _read_kv(env_file, environ):
    path = Path(env_file) if env_file is not None else Path(__file__).resolve().parents[1] / ".env"
    values: dict[str, str] = {}
    if path.is_file():
        for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            values[key] = value
    values.update(environ if environ is not None else os.environ)
    return values


def read_wechat_settings(env_file: str | Path | None = None,
                         environ: Mapping[str, str] | None = None) -> WechatConfig:
    values = _read_kv(env_file, environ)
    return WechatConfig(
        appid=values.get("YIFAZHILIAN_WECHAT_APPID", "").strip(),
        secret=values.get("YIFAZHILIAN_WECHAT_SECRET", "").strip(),
    )


def read_ai_settings(env_file: str | Path | None = None,
                     environ: Mapping[str, str] | None = None) -> AISettings:
    """Read inert KEY=VALUE text; never eval/interpolate or alter process env."""
    values = _read_kv(env_file, environ)
    prefix = "YIFAZHILIAN_AI_"
    provider = values.get(prefix + "PROVIDER", "mock").strip().lower()
    return AISettings(
        provider=provider,
        base_url=values.get(prefix + "BASE_URL", "").strip(),
        model=values.get(prefix + "MODEL", "").strip(),
        api_key=values.get(prefix + "API_KEY", "").strip(),
        display_name=values.get(prefix + "DISPLAY_NAME", "本地演示" if provider == "mock" else "外部模型").strip(),
    )


def read_mcp_settings(env_file: str | Path | None = None,
                      environ: Mapping[str, str] | None = None) -> MCPSettings:
    """Optional legal MCP. Empty command means the local SQLite knowledge base."""
    values = _read_kv(env_file, environ)
    prefix = "YIFAZHILIAN_LEGAL_MCP_"
    command = values.get(prefix + "COMMAND", "").strip()
    raw_args = values.get(prefix + "ARGS", "").strip()
    try:
        args = tuple(shlex.split(raw_args)) if raw_args else ()
    except ValueError:
        args = ()
    try:
        timeout = float(values.get(prefix + "TIMEOUT", "20").strip() or 20)
    except ValueError:
        timeout = 20.0
    return MCPSettings(command=command, args=args, timeout=max(3.0, min(timeout, 60.0)),
                       cwd=values.get(prefix + "CWD", "").strip(),
                       env={name: values[name].strip() for name in (prefix + "TOKEN", prefix + "UPSTREAM")
                            if values.get(name, "").strip()})
