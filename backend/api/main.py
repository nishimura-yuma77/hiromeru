"""FastAPIアプリケーション。Vercel Functions（`backend/main.py`）とローカルの共通の入口。"""

from fastapi import FastAPI

from api.exception_handlers import register_exception_handlers
from api.middleware import AuthCookieMiddleware, RequestContextMiddleware, RequestTimeoutMiddleware
from api.routers import approvals, auth, campaigns, health, memories, posts, sessions
from core.config import get_settings
from core.logging import configure_logging
from services.context import ServiceContext


def create_app(context: ServiceContext | None = None) -> FastAPI:
    """アプリケーションを作る。`context` はテストで依存（時刻・外部API）を差し替えるために使う。"""
    settings = context.settings if context is not None else get_settings()
    configure_logging(settings.log_level, json_output=settings.log_json)
    application = FastAPI(
        title="Hiromeru API",
        description="FastAPI service deployed as a Vercel Function.",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    if context is not None:
        application.state.context = context
    register_exception_handlers(application)
    for router in (
        health.router,
        auth.router,
        sessions.router,
        approvals.router,
        campaigns.router,
        posts.router,
        memories.router,
    ):
        application.include_router(router)
    # 後に追加したものが外側になる。request_id を最も外側で付与する。
    application.add_middleware(AuthCookieMiddleware)
    application.add_middleware(
        RequestTimeoutMiddleware, timeout_seconds=settings.request_timeout_seconds
    )
    application.add_middleware(RequestContextMiddleware)
    return application


app = create_app()
