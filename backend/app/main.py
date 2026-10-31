from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware
from app.api.routes import router
from app.api.navigation import router as navigation_router
from app.api.record_documents import router as records_router
from app.api.health_management import router as health_router
from app.api.volunteer import admin_router as volunteer_admin_router
from app.api.volunteer import router as volunteer_router
from app.api.admin import router as admin_router
from app.api.legal_help import router as legal_help_router
from app.services.record_ocr import LocalOCR
from app.config import (API_PREFIX, AISettings, MCPSettings, WechatConfig,
                        allowed_hosts, demo_auth_enabled, read_ai_settings, read_mcp_settings,
                        read_wechat_settings, runtime_mode)
from app.ai.providers.factory import create_provider
from app.db import Database
from app.services.knowledge_provider import create_knowledge_provider

logger = logging.getLogger("app.startup")
if not logging.getLogger().handlers:
    # uvicorn installs its own handlers; only configure when running bare.
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(application: FastAPI):
    yield
    provider = getattr(application.state, "knowledge_provider", None)
    if provider is not None:
        provider.close()


def create_app(database: Database | None = None, *, ai_settings: AISettings | None = None,
               wechat_config: WechatConfig | None = None,
               mcp_settings: MCPSettings | None = None) -> FastAPI:
    application = FastAPI(title="医法智联",
                          description="本地SQLite；可选外部AI；可选只读法律MCP。",
                          version="0.9.0", lifespan=lifespan)
    application.state.database = database if database is not None else Database()
    application.state.ai_provider = create_provider(ai_settings if ai_settings is not None else read_ai_settings())
    application.state.wechat_config = wechat_config if wechat_config is not None else read_wechat_settings()
    application.state.record_ocr = LocalOCR()
    application.state.knowledge_provider = create_knowledge_provider(
        mcp_settings if mcp_settings is not None else read_mcp_settings())
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts())

    @application.middleware("http")
    async def no_cache(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    application.include_router(router, prefix=API_PREFIX)
    application.include_router(navigation_router, prefix=API_PREFIX)
    application.include_router(records_router, prefix=API_PREFIX)
    application.include_router(health_router, prefix=API_PREFIX)
    application.include_router(volunteer_router, prefix=API_PREFIX)
    application.include_router(volunteer_admin_router, prefix=API_PREFIX)
    application.include_router(admin_router, prefix=API_PREFIX)
    application.include_router(legal_help_router, prefix=API_PREFIX)
    _log_startup(application)
    return application


def _log_startup(application: FastAPI) -> None:
    """One line of operator-visible state, and a loud warning about demo login.

    No tokens, keys or patient data are logged; only names and modes.
    """
    mode = runtime_mode()
    demo = demo_auth_enabled()
    knowledge = application.state.knowledge_provider
    logger.info("startup mode=%s demo_auth=%s ai=%s legal_retrieval=%s",
                mode, "on" if demo else "off",
                application.state.ai_provider.name, knowledge.mode("legal"))
    if demo:
        logger.warning("演示登录开启：/auth/send-code 固定返回 123456 并在响应里回显，"
                       "任何能访问本端口的人都能以任意手机号登录。接入短信通道后请设 "
                       "YIFAZHILIAN_DEMO_AUTH=0。")
    if mode == "production":
        logger.warning("mode=production 但本机仍使用 SQLite、未加密存储与本地演示语料；"
                       "请确认这是有意为之。")


app = create_app()
