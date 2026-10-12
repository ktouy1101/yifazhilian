from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware
from app.api.routes import router
from app.config import API_PREFIX
from app.db import Database


def create_app(database: Database | None = None) -> FastAPI:
    application = FastAPI(title="医法智联：仅合成数据演示 API",
                          description="本地SQLite持久化；无微信真实认证、无真实医疗服务、无外部AI调用。",
                          version="0.2.0")
    # Construction/import is disk-side-effect free; tests inject a temporary path.
    application.state.database = database if database is not None else Database()
    application.add_middleware(TrustedHostMiddleware,
                               allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    @application.middleware("http")
    async def no_cache(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    application.include_router(router, prefix=API_PREFIX)
    return application


app = create_app()
