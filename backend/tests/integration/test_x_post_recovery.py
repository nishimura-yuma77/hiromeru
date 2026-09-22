import asyncio
import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import OperationalError

from domain.enums import AgentTurnStatus, ApiIdempotencyStatus, ApiOperation
from models import (
    AgentItem,
    AgentTurn,
    ApiIdempotencyRequest,
    Post,
    PostEmbedding,
    PostMetric,
    PostTrackingLink,
)
from repositories.database import SessionLocal
from repositories.posts import PostRepository
from services.context import ServiceContext
from services.x_post_recovery import XPostRecoveryError, XPostRecoveryService
from tests.support.client import Account, post_body
from tests.support.fakes import FakeXApi, FixedClock


async def _request(marketer_id: int, key: str) -> ApiIdempotencyRequest:
    async with SessionLocal() as session:
        return (
            await session.execute(
                select(ApiIdempotencyRequest).where(
                    ApiIdempotencyRequest.marketer_id == marketer_id,
                    ApiIdempotencyRequest.operation == ApiOperation.PUBLISH_X_POST,
                    ApiIdempotencyRequest.idempotency_key == uuid.UUID(key),
                )
            )
        ).scalar_one()


async def _make_unknown(account: Account, x_api: FakeXApi) -> tuple[int, int, str, dict[str, Any]]:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    key = str(uuid.uuid4())
    body = post_body(campaign_id)
    x_api.outcome = "unknown"
    response = await account.publish_post(session_id, body, key)
    assert response.status_code == 504
    row = await _request(account.marketer_id, key)
    return row.id, campaign_id, key, body


async def test_結果不明を公開済みへ解決_Post関連と監査TurnとReplayを原子的に確定する(
    account: Account,
    x_api: FakeXApi,
    ctx: ServiceContext,
    clock: FixedClock,
) -> None:
    request_id, campaign_id, key, body = await _make_unknown(account, x_api)
    before = await _request(account.marketer_id, key)
    original_turn_id = before.agent_turn_id
    async with SessionLocal() as session:
        original_items = list(
            (
                await session.execute(
                    select(AgentItem.id, AgentItem.content)
                    .where(AgentItem.agent_turn_id == original_turn_id)
                    .order_by(AgentItem.id)
                )
            ).all()
        )

    result = await XPostRecoveryService(ctx).resolve_posted(
        request_id,
        x_post_id=f"confirmed-{uuid.uuid4().hex}",
        published_at=clock.now() - timedelta(minutes=5),
    )
    replay = await account.publish_post(before.session_id, body, key)

    assert result.status == ApiIdempotencyStatus.SUCCEEDED
    assert result.audit_turn_id != original_turn_id
    assert replay.status_code == 201
    assert replay.json()["data"]["post_id"] == result.post_id
    assert replay.json()["data"]["agent_turn_id"] == original_turn_id
    assert len(x_api.calls) == 1
    async with SessionLocal() as session:
        row = await session.get(ApiIdempotencyRequest, request_id)
        post = (
            await session.execute(select(Post).where(Post.api_idempotency_request_id == request_id))
        ).scalar_one()
        audit = await session.get(AgentTurn, result.audit_turn_id)
        original_items_after = list(
            (
                await session.execute(
                    select(AgentItem.id, AgentItem.content)
                    .where(AgentItem.agent_turn_id == original_turn_id)
                    .order_by(AgentItem.id)
                )
            ).all()
        )
        related_counts = [
            await session.scalar(
                select(func.count()).select_from(model).where(model.post_id == post.id)
            )
            for model in (PostEmbedding, PostTrackingLink, PostMetric)
        ]
    assert row is not None and row.status == ApiIdempotencyStatus.SUCCEEDED
    assert audit is not None and audit.status == AgentTurnStatus.COMPLETED
    assert original_items_after == original_items
    assert related_counts == [1, 1, 1]
    assert post.campaign_id == campaign_id
    history = (await account.client.get(f"/api/v1/agent-sessions/{before.session_id}")).json()[
        "data"
    ]
    audit_view = next(turn for turn in history["turns"] if turn["agent_turn_id"] == audit.id)
    assert [item["content"]["text"] for item in audit_view["items"]] == [
        "X投稿の手動照合を実施しました。"
    ]


async def test_結果不明を未公開へ解決_Postなしで監査Turnと確定失敗Replayを保存する(
    account: Account, x_api: FakeXApi, ctx: ServiceContext
) -> None:
    request_id, _campaign_id, key, body = await _make_unknown(account, x_api)
    row = await _request(account.marketer_id, key)

    result = await XPostRecoveryService(ctx).resolve_not_posted(request_id)
    replay = await account.publish_post(row.session_id, body, key)

    assert result.status == ApiIdempotencyStatus.FAILED
    assert replay.status_code == 502
    assert replay.json()["error"]["code"] == "X_POST_FAILED"
    assert replay.json()["error"]["agent_turn_id"] == row.agent_turn_id
    assert len(x_api.calls) == 1
    async with SessionLocal() as session:
        post_count = await session.scalar(
            select(func.count())
            .select_from(Post)
            .where(Post.api_idempotency_request_id == request_id)
        )
        audit = await session.get(AgentTurn, result.audit_turn_id)
    assert post_count == 0
    assert audit is not None and audit.status == AgentTurnStatus.COMPLETED


async def test_履歴でMaskされた元RequestはHash一致の標準入力相当Dataだけで公開済み解決できる(
    account: Account, x_api: FakeXApi, ctx: ServiceContext, clock: FixedClock
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    key = str(uuid.uuid4())
    body = post_body(campaign_id, body="連絡先は operator@example.com です")
    x_api.outcome = "unknown"
    await account.publish_post(session_id, body, key)
    row = await _request(account.marketer_id, key)
    service = XPostRecoveryService(ctx)

    with pytest.raises(XPostRecoveryError, match="stdin"):
        await service.resolve_posted(
            row.id, x_post_id=f"confirmed-{uuid.uuid4().hex}", published_at=clock.now()
        )

    result = await service.resolve_posted(
        row.id,
        x_post_id=f"confirmed-{uuid.uuid4().hex}",
        published_at=clock.now(),
        request_body=body,
    )

    assert result.status == ApiIdempotencyStatus.SUCCEEDED
    assert len(x_api.calls) == 1


async def test_結果不明の同時照合_CASで一方だけが成功する(
    account: Account, x_api: FakeXApi, ctx: ServiceContext, clock: FixedClock
) -> None:
    request_id, _campaign_id, _key, _body = await _make_unknown(account, x_api)
    service = XPostRecoveryService(ctx)

    results = await asyncio.gather(
        service.resolve_posted(
            request_id, x_post_id=f"confirmed-{uuid.uuid4().hex}", published_at=clock.now()
        ),
        service.resolve_not_posted(request_id),
        return_exceptions=True,
    )

    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, XPostRecoveryError) for result in results) == 1
    row = await _request(account.marketer_id, _key)
    async with SessionLocal() as session:
        audit_count = await session.scalar(
            select(func.count())
            .select_from(AgentTurn)
            .join(AgentItem, AgentItem.agent_turn_id == AgentTurn.id)
            .where(
                AgentTurn.session_id == row.session_id,
                AgentItem.idempotency_key == "reconciliation-decision",
            )
        )
    assert audit_count == 1


async def test_期限切れ保存待ちを運用復旧_Xを再呼出しせず通常経路と同じ保存を行う(
    account: Account,
    x_api: FakeXApi,
    ctx: ServiceContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    key = str(uuid.uuid4())
    original = PostRepository.insert_published

    async def failing(self: PostRepository, *args: Any, **kwargs: Any) -> Any:
        raise OperationalError("INSERT", {}, Exception("db down"))

    monkeypatch.setattr(PostRepository, "insert_published", failing)
    failed = await account.publish_post(session_id, post_body(campaign_id), key)
    monkeypatch.setattr(PostRepository, "insert_published", original)
    row = await _request(account.marketer_id, key)
    candidates = await XPostRecoveryService(ctx).list_candidates(company_id=account.company_id)

    result = await XPostRecoveryService(ctx).resume_persistence(row.id)

    assert failed.status_code == 500
    assert [candidate.request_id for candidate in candidates] == [row.id]
    assert candidates[0].recovery == "resume_persistence"
    assert result.status == ApiIdempotencyStatus.SUCCEEDED
    assert len(x_api.calls) == 1


async def test_不正external_resultの運用復旧_本文を漏らさずprocessingのまま保持する(
    account: Account,
    x_api: FakeXApi,
    ctx: ServiceContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    key = str(uuid.uuid4())

    async def failing(self: PostRepository, *args: Any, **kwargs: Any) -> Any:
        raise OperationalError("INSERT", {}, Exception("db down"))

    monkeypatch.setattr(PostRepository, "insert_published", failing)
    await account.publish_post(session_id, post_body(campaign_id), key)
    row = await _request(account.marketer_id, key)
    async with SessionLocal() as session, session.begin():
        await session.execute(
            update(ApiIdempotencyRequest)
            .where(ApiIdempotencyRequest.id == row.id)
            .values(external_result={"x_post_id": 1, "text": ["secret-provider-body"]})
        )

    with pytest.raises(XPostRecoveryError, match="remains retryable"):
        await XPostRecoveryService(ctx).resume_persistence(row.id)

    current = await _request(account.marketer_id, key)
    assert current.status == ApiIdempotencyStatus.PROCESSING
    assert current.response_body is None
    assert len(x_api.calls) == 1


async def test_公開済み解決のDB失敗_業務Dataと監査Turnと状態をすべてRollbackする(
    account: Account,
    x_api: FakeXApi,
    ctx: ServiceContext,
    clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_id, _campaign_id, key, _body = await _make_unknown(account, x_api)

    async def failing(self: PostRepository, *args: Any, **kwargs: Any) -> Any:
        raise OperationalError("INSERT", {}, Exception("db down"))

    monkeypatch.setattr(PostRepository, "insert_published", failing)
    with pytest.raises(XPostRecoveryError, match="no data was changed"):
        await XPostRecoveryService(ctx).resolve_posted(
            request_id, x_post_id=f"confirmed-{uuid.uuid4().hex}", published_at=clock.now()
        )

    row = await _request(account.marketer_id, key)
    async with SessionLocal() as session:
        post_count = await session.scalar(
            select(func.count())
            .select_from(Post)
            .where(Post.api_idempotency_request_id == request_id)
        )
        audit_count = await session.scalar(
            select(func.count())
            .select_from(AgentItem)
            .join(AgentTurn, AgentTurn.id == AgentItem.agent_turn_id)
            .where(
                AgentTurn.session_id == row.session_id,
                AgentItem.idempotency_key == "reconciliation-decision",
            )
        )
    assert row.status == ApiIdempotencyStatus.OUTCOME_UNKNOWN
    assert post_count == 0
    assert audit_count == 0
