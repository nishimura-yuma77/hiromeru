from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from api.main import app
from repositories.database import SessionLocal, get_db


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.clear()


async def test_死活確認_pathがapi_healthのとき200とstatus_okを返す(client: AsyncClient) -> None:
    response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_DB接続確認_pathがapi_health_dbのとき200とdatabase_okを返す(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/health/db")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


async def test_DB接続失敗時の応答_executeがOperationalErrorのとき503を返し内部情報を含めない(
    client: AsyncClient,
) -> None:
    class FailingSession:
        async def execute(self, *_args: object, **_kwargs: object) -> None:
            raise OperationalError("SELECT 1", {}, Exception("password=secret"))

    async def failing_get_db() -> AsyncIterator[FailingSession]:
        yield FailingSession()

    app.dependency_overrides[get_db] = failing_get_db

    response = await client.get("/api/health/db")

    assert response.status_code == 503
    assert response.json() == {"detail": "database unavailable"}


async def test_pgvector拡張の有無_pg_available_extensionsにvectorが1件あるとき利用できる() -> None:
    async with SessionLocal() as session:
        result = await session.execute(
            text("SELECT count(*) FROM pg_available_extensions WHERE name = 'vector'")
        )

    assert result.scalar_one() == 1
