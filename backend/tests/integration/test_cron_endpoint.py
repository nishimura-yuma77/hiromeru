import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import update

from domain.enums import PostMetricStatus
from models import PostMetric
from services.context import ServiceContext
from tests.support.client import Account, post_body
from tests.support.fakes import FakeEmbedding, FakeGa4, FakeXApi, FixedClock

CRON_SECRET = "cron-secret-at-least-16-characters"


@pytest.fixture(autouse=True)
async def _isolate_cron_candidates(ctx: ServiceContext, clock: FixedClock) -> None:
    async with ctx.session_factory() as session, session.begin():
        await session.execute(
            update(PostMetric)
            .where(PostMetric.status == PostMetricStatus.PENDING)
            .values(status=PostMetricStatus.FAILED, last_error_code="TEST_ISOLATION")
        )
        await session.execute(
            update(PostMetric)
            .where(
                PostMetric.status == PostMetricStatus.COMPLETED,
                PostMetric.memory_generated_at.is_(None),
                PostMetric.memory_failed_at.is_(None),
            )
            .values(memory_failed_at=clock.now(), memory_last_error_code="TEST_ISOLATION")
        )


async def _pending_post(account: Account, clock: FixedClock) -> int:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    response = await account.publish_post(session_id, post_body(campaign_id))
    assert response.status_code == 201, response.text
    clock.advance(7 * 24 * 60 * 60)
    return int(response.json()["data"]["post_id"])


@pytest.mark.parametrize(
    "authorization",
    [None, "", "Basic value", "Bearer", "Bearer ", "Bearer wrong", f"bearer {CRON_SECRET}"],
)
async def test_Cron認証不正は401でWorkerを開始しない(
    authorization: str | None,
    account: Account,
    anonymous: AsyncClient,
    ctx: ServiceContext,
    clock: FixedClock,
    x_api: FakeXApi,
    ga4: FakeGa4,
    embedding: FakeEmbedding,
) -> None:
    post_id = await _pending_post(account, clock)
    x_api.calls.clear()
    embedding.calls.clear()
    ctx.settings.cron_secret = SecretStr(CRON_SECRET)
    headers = {} if authorization is None else {"Authorization": authorization}

    response = await anonymous.get("/api/cron/post-metrics", headers=headers)

    assert response.status_code == 401
    assert response.content == b""
    assert response.headers["cache-control"] == "no-store"
    assert x_api.calls == ga4.calls == embedding.calls == []
    async with ctx.session_factory() as session:
        metric = await session.get(PostMetric, post_id)
        assert metric is not None
        assert metric.status == PostMetricStatus.PENDING
        assert metric.attempt_count == metric.memory_attempt_count == 0
        assert metric.execution_token is metric.lease_expires_at is None


async def test_Cron設定Secretが空またはPreviewなら正しいHeaderでも401(
    anonymous: AsyncClient, ctx: ServiceContext
) -> None:
    header = {"Authorization": f"Bearer {CRON_SECRET}"}

    empty = await anonymous.get("/api/cron/post-metrics", headers=header)
    ctx.settings.cron_secret = SecretStr(CRON_SECRET)
    ctx.settings.vercel_env = "preview"
    preview = await anonymous.get("/api/cron/post-metrics", headers=header)

    assert empty.status_code == preview.status_code == 401


async def test_Cron成功はMetricsとMemoryの安全なCounterだけを返す(
    account: Account,
    anonymous: AsyncClient,
    ctx: ServiceContext,
    clock: FixedClock,
    x_api: FakeXApi,
    ga4: FakeGa4,
    embedding: FakeEmbedding,
) -> None:
    post_id = await _pending_post(account, clock)
    x_api.calls.clear()
    embedding.calls.clear()
    x_api.impression_count = 100
    ga4.active_users = 25
    ctx.settings.cron_secret = SecretStr(CRON_SECRET)

    response = await anonymous.get(
        "/api/cron/post-metrics",
        headers={"Authorization": f"Bearer {CRON_SECRET}"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "status": "ok",
        "metrics_claimed": 1,
        "metrics_completed": 1,
        "metrics_failed": 0,
        "metrics_deferred": 0,
        "memories_claimed": 1,
        "memories_created": 1,
        "memories_failed": 0,
    }
    serialized = response.text
    for forbidden in ("x_post_id", "campaign_id", "utm_", "execution_token", "secret"):
        assert forbidden not in serialized
    async with ctx.session_factory() as session:
        metric = await session.get(PostMetric, post_id)
        assert metric is not None
        assert metric.status == PostMetricStatus.COMPLETED
        assert metric.memory_generated_at == clock.now()
        assert metric.execution_token is metric.lease_expires_at is None
    assert len(x_api.calls) == len(ga4.calls) == len(embedding.calls) == 1


async def test_CronのExact_Path_MethodとOpenAPI(
    anonymous: AsyncClient, ctx: ServiceContext
) -> None:
    ctx.settings.cron_secret = SecretStr(CRON_SECRET)
    headers = {"Authorization": f"Bearer {CRON_SECRET}"}

    wrong_path = await anonymous.get("/api/v1/cron/post-metrics", headers=headers)
    wrong_method = await anonymous.post("/api/cron/post-metrics", headers=headers)
    openapi = (await anonymous.get("/api/openapi.json")).json()

    assert wrong_path.status_code == 404
    assert wrong_method.status_code == 405
    assert set(openapi["paths"]["/api/cron/post-metrics"]) == {"get"}
    assert "/api/v1/cron/post-metrics" not in openapi["paths"]
