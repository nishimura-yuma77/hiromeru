"""結合テスト共通のFixture。実DB（Postgres）へ接続し、外部依存はFakeへ差し替える。"""

import uuid
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import AsyncExitStack
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from api.main import create_app
from core.config import Settings
from repositories.database import SessionLocal
from services.auth_service import AuthService
from services.context import ServiceContext
from tests.support.client import Account
from tests.support.fakes import (
    FakeAgentRunner,
    FakeContextCompactor,
    FakeEmbedding,
    FakeXApi,
    FixedClock,
    no_sleep,
)

ORIGIN = "http://localhost:3000"
PASSWORD = "correct-horse-battery"


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock()


@pytest.fixture
def embedding() -> FakeEmbedding:
    return FakeEmbedding()


@pytest.fixture
def x_api() -> FakeXApi:
    return FakeXApi()


@pytest.fixture
def agent() -> FakeAgentRunner:
    return FakeAgentRunner()


@pytest.fixture
def compactor() -> FakeContextCompactor:
    return FakeContextCompactor()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        auth_cookie_secret=SecretStr("test-secret-test-secret-test-secret-0123456789"),
        cookie_secure=False,
        allowed_origins=ORIGIN,
        log_json=False,
        log_level="WARNING",
    )


@pytest.fixture
def ctx(
    settings: Settings,
    clock: FixedClock,
    embedding: FakeEmbedding,
    x_api: FakeXApi,
    agent: FakeAgentRunner,
    compactor: FakeContextCompactor,
) -> ServiceContext:
    return ServiceContext(
        settings=settings,
        session_factory=SessionLocal,
        clock=clock,
        embedding=embedding,
        x_api=x_api,
        agent_runner=agent,
        context_compactor=compactor,
        sleep=no_sleep,
        new_uuid=uuid.uuid4,
    )


@pytest.fixture
def app(ctx: ServiceContext) -> FastAPI:
    return create_app(ctx)


@pytest.fixture
async def anonymous(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


type AccountFactory = Callable[[], Coroutine[Any, Any, Account]]


@pytest.fixture
async def new_account(app: FastAPI, ctx: ServiceContext) -> AsyncIterator[AccountFactory]:
    """会社・マーケターを作ってログインした状態のクライアントを作る。呼ぶたびに別の会社を作る。"""
    stack = AsyncExitStack()

    async def create() -> Account:
        email = f"{uuid.uuid4().hex}@example.com"
        record = await AuthService(ctx).create_marketer(
            company_name=f"company-{uuid.uuid4().hex[:8]}",
            marketer_name="マーケター",
            email=email,
            password=PASSWORD,
        )
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        client = await stack.enter_async_context(
            AsyncClient(transport=transport, base_url="http://test")
        )
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": PASSWORD},
            headers={"Origin": ORIGIN},
        )
        assert response.status_code == 200, response.text
        csrf = response.json()["data"]["csrf_token"]
        client.headers.update({"Origin": ORIGIN, "X-CSRF-Token": csrf})
        return Account(client, record.marketer_id, record.company_id, email, csrf)

    yield create
    await stack.aclose()


@pytest.fixture
async def account(new_account: AccountFactory) -> Account:
    return await new_account()
