"""DB接続。アプリケーション側では接続をプールしない（BE_STD 17.2）。"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from core.config import get_settings

settings = get_settings()

# Neon のプール接続（PgBouncer の transaction モード）を前提に、アプリケーション側では
# 接続をプールしない（規約17.2）。接続のプールは Neon 側に任せる。
engine = create_async_engine(
    settings.sqlalchemy_url(settings.database_url),
    poolclass=NullPool,
)
SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Request単位のDBセッションを返す（運用向けエンドポイント用）。"""
    async with SessionLocal() as session:
        yield session
