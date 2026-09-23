import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from domain.enums import PostMetricStatus
from models import AgentMemory, MemoryCampaign, MemoryPost, Post, PostMetric
from repositories.memories import MemoryRepository
from repositories.memory_cron import MemoryCronRepository, MemoryTransition
from services.context import ServiceContext
from services.evaluation_memory import EvaluationMemoryService
from tests.support.client import Account, post_body
from tests.support.fakes import FakeEmbedding, FixedClock


@pytest.fixture(autouse=True)
async def _isolate_memory_candidates(ctx: ServiceContext, clock: FixedClock) -> None:
    async with ctx.session_factory() as session, session.begin():
        await session.execute(
            update(PostMetric)
            .where(
                PostMetric.status == PostMetricStatus.COMPLETED,
                PostMetric.memory_generated_at.is_(None),
                PostMetric.memory_failed_at.is_(None),
            )
            .values(
                memory_failed_at=clock.now(),
                memory_last_error_code="TEST_ISOLATION",
                execution_token=None,
                lease_expires_at=None,
            )
        )


async def _completed_post(
    account: Account,
    ctx: ServiceContext,
    clock: FixedClock,
    *,
    x_pv_count: int = 1200,
    landing_user_count: int = 45,
) -> tuple[int, int]:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id, title="経験者Webエンジニア採用")
    response = await account.publish_post(
        session_id,
        post_body(
            campaign_id,
            body="フルリモートで働けます。応募してください",
        ),
    )
    assert response.status_code == 201, response.text
    post_id = int(response.json()["data"]["post_id"])
    async with ctx.session_factory() as session, session.begin():
        await session.execute(
            update(PostMetric)
            .where(PostMetric.post_id == post_id)
            .values(
                status=PostMetricStatus.COMPLETED,
                x_pv_count=x_pv_count,
                landing_user_count=landing_user_count,
                measured_at=clock.now(),
                execution_token=None,
                lease_expires_at=None,
            )
        )
        await session.execute(
            update(Post)
            .where(Post.id == post_id)
            .values(body="フルリモートで働けます https://example.com/secret\n応募してください")
        )
    return post_id, campaign_id


async def _metric(ctx: ServiceContext, post_id: int) -> dict[str, object]:
    async with ctx.session_factory() as session:
        metric = await session.get(PostMetric, post_id)
        assert metric is not None
        return {
            "status": metric.status,
            "generated": metric.memory_generated_at,
            "failed": metric.memory_failed_at,
            "attempts": metric.memory_attempt_count,
            "next": metric.memory_next_attempt_at,
            "error": metric.memory_last_error_code,
            "token": metric.execution_token,
            "lease": metric.lease_expires_at,
        }


async def test_評価記憶と両RelationとMarkerを原子的に保存する(
    account: Account,
    ctx: ServiceContext,
    clock: FixedClock,
    embedding: FakeEmbedding,
) -> None:
    post_id, campaign_id = await _completed_post(account, ctx, clock)
    embedding.calls.clear()

    result = await EvaluationMemoryService(ctx).run(max_items=1)

    assert result.claimed == result.created == 1
    assert result.failed == 0
    assert len(embedding.calls) == 1
    content = embedding.calls[0]
    assert content == (
        "施策タイトル: 経験者Webエンジニア採用\n"
        "投稿本文: フルリモートで働けます 応募してください\n"
        "初週PV: 1200\n"
        "流入ユーザー: 45\n"
        "流入率: 45/1200"
    )
    async with ctx.session_factory() as session:
        memory = (
            await session.execute(
                select(AgentMemory)
                .join(MemoryPost, MemoryPost.memory_id == AgentMemory.id)
                .where(MemoryPost.post_id == post_id)
            )
        ).scalar_one()
        assert await session.get(MemoryCampaign, (memory.id, campaign_id)) is not None
        assert await session.get(MemoryPost, (memory.id, post_id)) is not None
    metric = await _metric(ctx, post_id)
    assert metric["generated"] == clock.now()
    assert metric["failed"] is None
    assert metric["attempts"] == 1
    assert metric["token"] is metric["lease"] is None


async def test_Embedding失敗を再試行し最大試行でもMetricsはcompletedを維持する(
    account: Account,
    ctx: ServiceContext,
    clock: FixedClock,
    embedding: FakeEmbedding,
) -> None:
    post_id, _ = await _completed_post(account, ctx, clock, x_pv_count=0, landing_user_count=0)
    embedding.fail = True

    first = await EvaluationMemoryService(ctx).run(max_items=1)
    assert first.claimed == 1 and first.created == first.failed == 0
    metric = await _metric(ctx, post_id)
    assert metric["status"] == PostMetricStatus.COMPLETED
    assert metric["next"] == clock.now() + timedelta(hours=1)
    assert metric["error"] == "EMBEDDING_FAILED"
    clock.advance(60 * 60)
    await EvaluationMemoryService(ctx).run(max_items=1)
    clock.advance(2 * 60 * 60)
    third = await EvaluationMemoryService(ctx).run(max_items=1)

    metric = await _metric(ctx, post_id)
    assert third.failed == 1
    assert metric["status"] == PostMetricStatus.COMPLETED
    assert metric["failed"] == clock.now()
    assert metric["attempts"] == 3
    assert metric["next"] is None
    assert "secret" not in str(metric)


async def test_Memory保存失敗は全InsertをRollbackして別TransactionでRetry化する(
    account: Account,
    ctx: ServiceContext,
    clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post_id, _ = await _completed_post(account, ctx, clock)
    original = MemoryRepository.insert

    async def fail_after_insert(self: MemoryRepository, *args, **kwargs):
        await original(self, *args, **kwargs)
        raise RuntimeError("provider-secret")

    monkeypatch.setattr(MemoryRepository, "insert", fail_after_insert)
    result = await EvaluationMemoryService(ctx).run(max_items=1)

    assert result.claimed == 1 and result.created == result.failed == 0
    async with ctx.session_factory() as session:
        assert (
            await session.scalar(
                select(func.count(MemoryPost.memory_id)).where(MemoryPost.post_id == post_id)
            )
            == 0
        )
    metric = await _metric(ctx, post_id)
    assert metric["generated"] is None
    assert metric["error"] == "MEMORY_SAVE_FAILED"
    assert "secret" not in str(metric)


async def test_期限切れStale_TokenはMemoryもMarkerも保存できない(
    account: Account, ctx: ServiceContext, clock: FixedClock
) -> None:
    post_id, _ = await _completed_post(account, ctx, clock)
    async with ctx.session_factory() as session, session.begin():
        claim = (
            await MemoryCronRepository(session).claim(
                now=clock.now(),
                lease_expires_at=clock.now() + timedelta(seconds=1),
                max_attempts=3,
                limit=1,
                new_uuid=uuid.uuid4,
            )
        )[0]
    clock.advance(1)
    async with ctx.session_factory() as session, session.begin():
        transition, memory_id = await MemoryCronRepository(session).save_created(
            claim,
            content="保存禁止",
            embedding=[0.0] * ctx.settings.embedding_dimensions,
            now=clock.now(),
        )

    assert transition == MemoryTransition.LEASE_LOST
    assert memory_id is None
    assert (await _metric(ctx, post_id))["generated"] is None
    async with ctx.session_factory() as session:
        assert (
            await session.scalar(
                select(func.count(MemoryPost.memory_id)).where(MemoryPost.post_id == post_id)
            )
            == 0
        )


async def test_2Sessionは同じ評価記憶候補を同時Claimしない(
    account: Account, ctx: ServiceContext, clock: FixedClock
) -> None:
    post_id, _ = await _completed_post(account, ctx, clock)
    expires = clock.now() + timedelta(seconds=ctx.settings.lease_seconds)

    async with ctx.session_factory() as first_session, first_session.begin():
        first = await MemoryCronRepository(first_session).claim(
            now=clock.now(),
            lease_expires_at=expires,
            max_attempts=3,
            limit=1,
            new_uuid=uuid.uuid4,
        )
        async with ctx.session_factory() as second_session, second_session.begin():
            second = await MemoryCronRepository(second_session).claim(
                now=clock.now(),
                lease_expires_at=expires,
                max_attempts=3,
                limit=1,
                new_uuid=uuid.uuid4,
            )

    assert [claim.post_id for claim in first] == [post_id]
    assert second == []


async def test_生成済み記憶を削除してもMarkerを残し再生成しない(
    account: Account,
    ctx: ServiceContext,
    clock: FixedClock,
    embedding: FakeEmbedding,
) -> None:
    post_id, _ = await _completed_post(account, ctx, clock)
    embedding.calls.clear()
    assert (await EvaluationMemoryService(ctx).run(max_items=1)).created == 1
    async with ctx.session_factory() as session:
        memory_id = int(
            await session.scalar(select(MemoryPost.memory_id).where(MemoryPost.post_id == post_id))
            or 0
        )

    response = await account.client.delete(f"/api/v1/memories/{memory_id}")
    assert response.status_code == 200
    calls = len(embedding.calls)
    rerun = await EvaluationMemoryService(ctx).run(max_items=1)

    assert rerun.claimed == 0
    assert len(embedding.calls) == calls
    assert (await _metric(ctx, post_id))["generated"] == clock.now()
    async with ctx.session_factory() as session:
        assert await session.get(AgentMemory, memory_id) is None


async def test_最大試行中断はEmbeddingなしでMemoryだけをfailedへする(
    account: Account,
    ctx: ServiceContext,
    clock: FixedClock,
    embedding: FakeEmbedding,
) -> None:
    post_id, _ = await _completed_post(account, ctx, clock)
    embedding.calls.clear()
    async with ctx.session_factory() as session, session.begin():
        await session.execute(
            update(PostMetric)
            .where(PostMetric.post_id == post_id)
            .values(
                memory_attempt_count=3,
                execution_token=uuid.uuid4(),
                lease_expires_at=clock.now() - timedelta(seconds=1),
            )
        )

    result = await EvaluationMemoryService(ctx).run(max_items=1)
    metric = await _metric(ctx, post_id)

    assert result.claimed == 0
    assert metric["status"] == PostMetricStatus.COMPLETED
    assert metric["failed"] == clock.now()
    assert metric["error"] == "WORKER_INTERRUPTED"
    assert embedding.calls == []
