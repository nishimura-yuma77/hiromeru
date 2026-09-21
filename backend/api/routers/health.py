"""運用向けエンドポイント（API_DESIGN 2.11）。認証・CSRF・共通Response形式を使わない。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from repositories.database import get_db

router = APIRouter(prefix="/api", tags=["ops"])


@router.get("/health")
def health() -> dict[str, str]:
    """プロセスの死活を確認する。DBへ接続しない。"""
    return {"status": "ok"}


@router.get("/health/db")
async def database_health(db: AsyncSession = Depends(get_db)) -> dict[str, str]:  # noqa: B008
    """DBへの接続を確認する。接続先や例外の内容は返さない。"""
    try:
        await db.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="database unavailable"
        ) from error
    return {"status": "ok", "database": "ok"}
