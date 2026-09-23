import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from clients.errors import (
    Ga4ConfigurationError,
    Ga4RetryableProviderError,
    XApiRetryableProviderError,
)
from domain.cron import retry_delay
from domain.enums import PostMetricStatus
from models import PostMetric
from repositories.metric_cron import MetricCronRepository, MetricTransition
from services.context import ServiceContext
from services.metric_collection import MetricCollectionService
from tests.support.client import Account, post_body
from tests.support.fakes import FakeGa4, FakeXApi, FixedClock


@pytest.fixture(autouse=True)
async def _isolate_pending_metrics(ctx: ServiceContext) -> None:
    async with ctx.session_factory() as session, session.begin():
        await session.execute(
            update(PostMetric)
            .where(PostMetric.status == PostMetricStatus.PENDING)
            .values(
                status=PostMetricStatus.FAILED,
                execution_token=None,
                lease_expires_at=None,
                next_attempt_at=None,
                last_error_code="TEST_ISOLATION",
            )
        )


async def _due_post(account: Account, clock: FixedClock, *, advance: bool = True) -> int:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    response = await account.publish_post(session_id, post_body(campaign_id))
    assert response.status_code == 201, response.text
    if advance:
        clock.advance(7 * 24 * 60 * 60)
    return int(response.json()["data"]["post_id"])


async def _metric(ctx: ServiceContext, post_id: int) -> dict[str, object]:
    async with ctx.session_factory() as session:
        metric = await session.get(PostMetric, post_id)
        assert metric is not None
        return {
            "status": metric.status,
            "x": metric.x_pv_count,
            "ga4": metric.landing_user_count,
            "measured_at": metric.measured_at,
            "token": metric.execution_token,
            "lease": metric.lease_expires_at,
            "attempts": metric.attempt_count,
            "next": metric.next_attempt_at,
            "error": metric.last_error_code,
        }


async def test_Metrics両Provider成功で完了し0も取得済みとして保存する(
    account: Account,
    ctx: ServiceContext,
    clock: FixedClock,
    x_api: FakeXApi,
    ga4: FakeGa4,
) -> None:
    post_id = await _due_post(account, clock)
    x_api.calls.clear()
    x_api.impression_count = 0
    ga4.active_users = 0

    result = await MetricCollectionService(ctx).run(max_items=1)

    metric = await _metric(ctx, post_id)
    assert result.claimed == result.completed == 1
    assert result.failed == result.deferred == 0
    assert metric == {
        "status": PostMetricStatus.COMPLETED,
        "x": 0,
        "ga4": 0,
        "measured_at": clock.now(),
        "token": None,
        "lease": None,
        "attempts": 1,
        "next": None,
        "error": None,
    }
    assert len(x_api.calls) == len(ga4.calls) == 1


async def test_X成功GA4失敗は部分値を保持し次回GA4だけ再試行する(
    account: Account,
    ctx: ServiceContext,
    clock: FixedClock,
    x_api: FakeXApi,
    ga4: FakeGa4,
) -> None:
    post_id = await _due_post(account, clock)
    x_api.calls.clear()
    x_api.impression_count = 10
    ga4.error = Ga4RetryableProviderError("secret-provider-body")

    first = await MetricCollectionService(ctx).run(max_items=1)

    metric = await _metric(ctx, post_id)
    assert first.deferred == 1
    assert metric["x"] == 10
    assert metric["ga4"] is None
    assert metric["next"] == clock.now() + timedelta(hours=1)
    assert metric["error"] == "GA4_PROVIDER_RETRYABLE"
    assert "secret-provider-body" not in str(metric)

    ga4.error = None
    ga4.active_users = 4
    clock.advance(60 * 60)
    second = await MetricCollectionService(ctx).run(max_items=1)

    assert second.completed == 1
    assert (await _metric(ctx, post_id))["status"] == PostMetricStatus.COMPLETED
    assert len(x_api.calls) == 1
    assert len(ga4.calls) == 2


async def test_GA4成功X失敗は部分値を保持し次回Xだけ再試行する(
    account: Account,
    ctx: ServiceContext,
    clock: FixedClock,
    x_api: FakeXApi,
    ga4: FakeGa4,
) -> None:
    post_id = await _due_post(account, clock)
    x_api.calls.clear()
    x_api.metrics_error = XApiRetryableProviderError("secret")
    ga4.active_users = 8

    first = await MetricCollectionService(ctx).run(max_items=1)
    metric = await _metric(ctx, post_id)

    assert first.deferred == 1
    assert metric["x"] is None
    assert metric["ga4"] == 8
    x_api.metrics_error = None
    x_api.impression_count = 20
    clock.advance(60 * 60)

    assert (await MetricCollectionService(ctx).run(max_items=1)).completed == 1
    assert len(x_api.calls) == 2
    assert len(ga4.calls) == 1


async def test_再試行不能Errorは成功した部分値を保持して即時failed(
    account: Account,
    ctx: ServiceContext,
    clock: FixedClock,
    x_api: FakeXApi,
    ga4: FakeGa4,
) -> None:
    post_id = await _due_post(account, clock)
    x_api.impression_count = 12
    ga4.error = Ga4ConfigurationError("credential=secret")

    result = await MetricCollectionService(ctx).run(max_items=1)
    metric = await _metric(ctx, post_id)

    assert result.failed == 1
    assert metric["status"] == PostMetricStatus.FAILED
    assert metric["x"] == 12
    assert metric["ga4"] is None
    assert metric["error"] == "GA4_CONFIGURATION_ERROR"
    assert "secret" not in str(metric)


@pytest.mark.parametrize(
    ("attempt", "hours"), [(1, 1), (2, 2), (3, 4), (4, 8), (5, 16), (6, 24), (7, 24)]
)
def test_Metrics再試行Backoffは1hから指数増加し24hを上限とする(
    attempt: int, hours: int
) -> None:
    assert retry_delay(attempt) == timedelta(hours=hours)


async def test_Metrics再試行は1h_2h後で最大試行に達するとfailed(
    account: Account,
    ctx: ServiceContext,
    clock: FixedClock,
    x_api: FakeXApi,
    ga4: FakeGa4,
) -> None:
    post_id = await _due_post(account, clock)
    x_api.calls.clear()
    x_api.metrics_error = XApiRetryableProviderError("x-secret")
    ga4.error = Ga4RetryableProviderError("ga-secret")

    first = await MetricCollectionService(ctx).run(max_items=1)
    assert first.deferred == 1
    assert (await _metric(ctx, post_id))["next"] == clock.now() + timedelta(hours=1)
    clock.advance(60 * 60)
    second = await MetricCollectionService(ctx).run(max_items=1)
    assert second.deferred == 1
    assert (await _metric(ctx, post_id))["next"] == clock.now() + timedelta(hours=2)
    clock.advance(2 * 60 * 60)
    third = await MetricCollectionService(ctx).run(max_items=1)

    metric = await _metric(ctx, post_id)
    assert third.failed == 1
    assert metric["status"] == PostMetricStatus.FAILED
    assert metric["attempts"] == 3
    assert metric["next"] is None
    assert len(x_api.calls) == len(ga4.calls) == 3


async def test_最大試行中断Rowは外部Callなしでfailedへ終端化する(
    account: Account,
    ctx: ServiceContext,
    clock: FixedClock,
    x_api: FakeXApi,
    ga4: FakeGa4,
) -> None:
    post_id = await _due_post(account, clock)
    x_api.calls.clear()
    async with ctx.session_factory() as session, session.begin():
        await session.execute(
            update(PostMetric)
            .where(PostMetric.post_id == post_id)
            .values(
                attempt_count=3,
                execution_token=uuid.uuid4(),
                lease_expires_at=clock.now() - timedelta(seconds=1),
            )
        )

    result = await MetricCollectionService(ctx).run(max_items=1)

    metric = await _metric(ctx, post_id)
    assert result.claimed == 0
    assert metric["status"] == PostMetricStatus.FAILED
    assert metric["error"] == "WORKER_INTERRUPTED"
    assert x_api.calls == []
    assert ga4.calls == []


async def test_2SessionのClaimはSKIP_LOCKEDで同じRowを取得しない(
    account: Account, ctx: ServiceContext, clock: FixedClock
) -> None:
    first_id = await _due_post(account, clock, advance=False)
    second_id = await _due_post(account, clock, advance=False)
    clock.advance(7 * 24 * 60 * 60)
    now = clock.now()
    expires = now + timedelta(seconds=ctx.settings.lease_seconds)

    async with ctx.session_factory() as first_session, first_session.begin():
        first = await MetricCronRepository(first_session).claim(
            now=now,
            lease_expires_at=expires,
            max_attempts=3,
            limit=1,
            new_uuid=uuid.uuid4,
        )
        async with ctx.session_factory() as second_session, second_session.begin():
            second = await MetricCronRepository(second_session).claim(
                now=now,
                lease_expires_at=expires,
                max_attempts=3,
                limit=1,
                new_uuid=uuid.uuid4,
            )

    assert [claim.post_id for claim in first] == [first_id]
    assert [claim.post_id for claim in second] == [second_id]


async def test_期限切れまたはOld_TokenのWriteは拒否する(
    account: Account, ctx: ServiceContext, clock: FixedClock
) -> None:
    post_id = await _due_post(account, clock)
    now = clock.now()
    async with ctx.session_factory() as session, session.begin():
        claim = (
            await MetricCronRepository(session).claim(
                now=now,
                lease_expires_at=now + timedelta(seconds=1),
                max_attempts=3,
                limit=1,
                new_uuid=uuid.uuid4,
            )
        )[0]
    clock.advance(1)
    async with ctx.session_factory() as session, session.begin():
        expired = await MetricCronRepository(session).save_provider_success(
            post_id, claim.token, provider="x", value=999, now=clock.now()
        )
    async with ctx.session_factory() as session, session.begin():
        replacement = (
            await MetricCronRepository(session).claim(
                now=clock.now(),
                lease_expires_at=clock.now() + timedelta(seconds=330),
                max_attempts=3,
                limit=1,
                new_uuid=uuid.uuid4,
            )
        )[0]
    async with ctx.session_factory() as session, session.begin():
        stale = await MetricCronRepository(session).finish_failure(
            post_id,
            claim.token,
            now=clock.now(),
            error_code="SHOULD_NOT_SAVE",
            retryable=False,
            max_attempts=3,
        )

    assert expired == stale == MetricTransition.LEASE_LOST
    assert replacement.token != claim.token
    metric = await _metric(ctx, post_id)
    assert metric["x"] is None
    assert metric["error"] is None


async def test_Invocation上限を超えてClaimしない(
    account: Account,
    ctx: ServiceContext,
    clock: FixedClock,
) -> None:
    post_ids = [await _due_post(account, clock, advance=False) for _ in range(3)]
    clock.advance(7 * 24 * 60 * 60)

    result = await MetricCollectionService(ctx).run(max_items=2)
    async with ctx.session_factory() as session:
        statuses = list(
            (
                await session.execute(
                    select(PostMetric.status).where(PostMetric.post_id.in_(post_ids))
                )
            ).scalars()
        )

    assert result.claimed == result.completed == 2
    assert statuses.count(PostMetricStatus.COMPLETED) == 2
    assert statuses.count(PostMetricStatus.PENDING) == 1
