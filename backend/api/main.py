from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from repositories.database import get_db

app = FastAPI(
    title="Hiromeru API",
    description="FastAPI service deployed as a Vercel Function.",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/health/db")
async def database_health(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    try:
        await db.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        ) from error

    return {"status": "ok", "database": "ok"}
