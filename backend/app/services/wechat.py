"""WeChat code2session exchange. Thin wrapper over the official endpoint.
Tests inject a fake transport to avoid real network calls."""
import urllib.parse
import urllib.request
import json
from app.config import WechatConfig

CODE2SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"


class WechatLoginError(Exception):
    def __init__(self, message: str, code: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code


def exchange_code(code: str, config: WechatConfig, transport=None) -> dict:
    """Return {openid, session_key} or raise WechatLoginError."""
    if not config.enabled:
        raise WechatLoginError("微信登录未配置", 503)
    if not code or len(code) > 128:
        raise WechatLoginError("code 无效")
    query = urllib.parse.urlencode({
        "appid": config.appid, "secret": config.secret,
        "js_code": code, "grant_type": "authorization_code"
    })
    url = f"{CODE2SESSION_URL}?{query}"

    def default_fetch():
        with urllib.request.urlopen(url, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    payload = (transport or default_fetch)()
    openid = payload.get("openid")
    if not openid:
        errcode = payload.get("errcode", -1)
        errmsg = payload.get("errmsg", "unknown")
        raise WechatLoginError(f"微信登录失败({errcode}): {errmsg}", 401)
    return {"openid": openid, "session_key": payload.get("session_key", "")}
