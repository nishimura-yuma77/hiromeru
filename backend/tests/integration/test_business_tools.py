from typing import Any, cast

import pytest
from pydantic import BaseModel
from sqlalchemy import func, select, update

from agent_runtime.executor import ToolExecutor
from agent_runtime.tools import (
    ToolCall,
    ToolDefinition,
    ToolDomainError,
    ToolProvenance,
    ToolProvenanceRef,
    TrustedToolContext,
)
from api.sse import NullReporter
from domain.enums import (
    AgentContentSource,
    AgentItemType,
    AgentTurnStatus,
    AgentType,
    ApiIdempotencyStatus,
    PostMetricStatus,
)
from models import (
    AgentMemory,
    AgentTurn,
    ApiIdempotencyRequest,
    MemoryCampaign,
    MemoryPost,
    Post,
    PostMetric,
)
from repositories.agent import SessionRepository, TurnRepository
from services.context import ServiceContext
from tests.conftest import AccountFactory
from tests.support.client import Account, post_body
from tests.support.db import archive_campaign, insert_memory
from tests.support.fakes import FakeEmbedding, FixedClock


def _context(
    ctx: ServiceContext,
    account: Account,
    session_id: int,
    turn_id: int,
    provenance: tuple[ToolProvenanceRef, ...] = (),
) -> TrustedToolContext:
    return TrustedToolContext(
        company_id=account.company_id,
        marketer_id=account.marketer_id,
        session_id=session_id,
        parent_session_id=None,
        turn_id=turn_id,
        agent_type=AgentType.PARENT,
        turn_status=AgentTurnStatus.RUNNING,
        turn_started_at=ctx.clock.now(),
        provenance=provenance,
    )


async def _execute(
    ctx: ServiceContext,
    name: str,
    context: TrustedToolContext,
    arguments: dict[str, Any],
) -> Any:
    definition = cast(ToolDefinition, ctx.tool_registry.get(name))
    tool_input = definition.input_model.model_validate(arguments)
    return await definition.handler.execute(context, cast(BaseModel, tool_input))


async def _error(
    ctx: ServiceContext,
    name: str,
    context: TrustedToolContext,
    arguments: dict[str, Any],
) -> str:
    with pytest.raises(ToolDomainError) as captured:
        await _execute(ctx, name, context, arguments)
    return captured.value.code


async def _new_turn(ctx: ServiceContext, account: Account, session_id: int) -> tuple[int, int]:
    async with ctx.session_factory() as session, session.begin():
        locked = await SessionRepository(session).get_parent(
            account.marketer_id, session_id, lock=True
        )
        assert locked is not None
        turn = await TurnRepository(session).create_turn(session_id, ctx.clock.now())
        item = await TurnRepository(session).append_item(
            turn.id,
            key="tool-test-user",
            item_type=AgentItemType.USER_MESSAGE,
            source=AgentContentSource.USER_INPUT,
            content={"text": "この内容を覚えておいて。"},
            now=ctx.clock.now(),
        )
    return turn.id, item.id


async def _set_publication(ctx: ServiceContext, post_id: int, status: ApiIdempotencyStatus) -> None:
    async with ctx.session_factory() as session, session.begin():
        request_id = await session.scalar(
            select(Post.api_idempotency_request_id).where(Post.id == post_id)
        )
        assert request_id is not None
        values: dict[str, Any] = {"status": status}
        if status == ApiIdempotencyStatus.PROCESSING:
            values.update(http_status=None, response_body=None, completed_at=None)
        await session.execute(
            update(ApiIdempotencyRequest)
            .where(ApiIdempotencyRequest.id == request_id)
            .values(**values)
        )


async def _memory_counts(ctx: ServiceContext, company_id: int) -> tuple[int, int, int]:
    async with ctx.session_factory() as session:
        memory_ids = select(AgentMemory.id).where(AgentMemory.company_id == company_id)
        memories = await session.scalar(
            select(func.count())
            .select_from(AgentMemory)
            .where(AgentMemory.company_id == company_id)
        )
        campaigns = await session.scalar(
            select(func.count())
            .select_from(MemoryCampaign)
            .where(MemoryCampaign.memory_id.in_(memory_ids))
        )
        posts = await session.scalar(
            select(func.count()).select_from(MemoryPost).where(MemoryPost.memory_id.in_(memory_ids))
        )
    return int(memories or 0), int(campaigns or 0), int(posts or 0)


async def test_業務ToolはRepository境界で9種の主要経路を処理する(  # noqa: PLR0915
    account: Account, ctx: ServiceContext, embedding: FakeEmbedding
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id, title="記憶対象の施策")
    response = await account.publish_post(session_id, post_body(campaign_id, body="柔軟な働き方"))
    assert response.status_code == 201
    post_id = int(response.json()["data"]["post_id"])

    async with ctx.session_factory() as session, session.begin():
        locked = await SessionRepository(session).get_parent(
            account.marketer_id, session_id, lock=True
        )
        assert locked is not None
        turn = await TurnRepository(session).create_turn(session_id, ctx.clock.now())
        remember = await TurnRepository(session).append_item(
            turn.id,
            key="remember-request",
            item_type=AgentItemType.USER_MESSAGE,
            source=AgentContentSource.USER_INPUT,
            content={"text": "この方針を覚えておいて"},
            now=ctx.clock.now(),
        )
    provenance = (ToolProvenanceRef(source=ToolProvenance.USER_INPUT, item_id=remember.id),)
    context = _context(ctx, account, session_id, turn.id, provenance)

    before_reads = len(embedding.calls)
    campaign = await _execute(ctx, "get_campaign", context, {"campaign_id": campaign_id})
    post = await _execute(ctx, "get_post", context, {"post_id": post_id})
    metrics = await _execute(ctx, "get_marketing_metrics", context, {"post_id": post_id})
    assert campaign.campaign.campaign_id == campaign_id
    assert post.post.post_id == post_id
    assert post.post.tracking.utm_source == "x"
    assert post.post.metrics.status == "pending"
    assert metrics.metrics.status == "pending"
    assert len(embedding.calls) == before_reads

    async with ctx.session_factory() as session, session.begin():
        denied_remember = await TurnRepository(session).append_item(
            turn.id,
            key="denied-remember",
            item_type=AgentItemType.USER_MESSAGE,
            source=AgentContentSource.USER_INPUT,
            content={"text": "この方針は覚えていない"},
            now=ctx.clock.now(),
        )
    denied_context = _context(
        ctx,
        account,
        session_id,
        turn.id,
        (ToolProvenanceRef(source=ToolProvenance.USER_INPUT, item_id=denied_remember.id),),
    )
    try:
        await _execute(
            ctx,
            "save_long_term_memory",
            denied_context,
            {
                "source_item_id": denied_remember.id,
                "content": "保存してはいけない内容",
                "campaign_ids": [],
                "post_ids": [],
            },
        )
    except ToolDomainError as error:
        assert error.code == "MEMORY_SAVE_NOT_REQUESTED"
    else:
        raise AssertionError("non-request text must not authorize memory save")

    saved = await _execute(
        ctx,
        "save_long_term_memory",
        context,
        {
            "source_item_id": remember.id,
            "content": "担当は user@example.com。柔軟な働き方を優先する",
            "campaign_ids": [campaign_id],
            "post_ids": [post_id],
        },
    )
    memories = await _execute(
        ctx,
        "search_long_term_memory",
        context,
        {"query": "柔軟な働き方を優先する", "limit": 5},
    )
    assert memories.memories[0].memory_id == saved.memory_id
    assert "[EMAIL]" in memories.memories[0].content
    assert memories.memories[0].campaign_ids == (campaign_id,)
    assert memories.memories[0].post_ids == (post_id,)

    campaigns = await _execute(
        ctx,
        "search_campaigns",
        context,
        {"query": "記憶対象の施策", "limit": 5},
    )
    posts = await _execute(
        ctx,
        "search_posts",
        context,
        {"query": "柔軟な働き方", "campaign_id": campaign_id, "limit": 5},
    )
    assert any(item.campaign_id == campaign_id for item in campaigns.campaigns)
    assert any(item.post_id == post_id for item in posts.posts)

    async with ctx.session_factory() as session, session.begin():
        denied_forget = await TurnRepository(session).append_item(
            turn.id,
            key="denied-forget",
            item_type=AgentItemType.USER_MESSAGE,
            source=AgentContentSource.USER_INPUT,
            content={"text": f"記憶 {saved.memory_id} を削除してはいけない"},
            now=ctx.clock.now(),
        )
        forget = await TurnRepository(session).append_item(
            turn.id,
            key="forget-request",
            item_type=AgentItemType.USER_MESSAGE,
            source=AgentContentSource.USER_INPUT,
            content={"text": f"記憶 {saved.memory_id} を削除して"},
            now=ctx.clock.now(),
        )
    denied_delete_context = _context(
        ctx,
        account,
        session_id,
        turn.id,
        (ToolProvenanceRef(source=ToolProvenance.USER_INPUT, item_id=denied_forget.id),),
    )
    try:
        await _execute(
            ctx,
            "delete_long_term_memory",
            denied_delete_context,
            {"memory_id": saved.memory_id},
        )
    except ToolDomainError as error:
        assert error.code == "MEMORY_DELETE_NOT_APPROVED"
    else:
        raise AssertionError("negated instruction must not authorize memory deletion")
    async with ctx.session_factory() as session, session.begin():
        mismatch = await TurnRepository(session).append_item(
            turn.id,
            key="mismatched-forget",
            item_type=AgentItemType.USER_MESSAGE,
            source=AgentContentSource.USER_INPUT,
            content={"text": f"記憶 {saved.memory_id + 1} を削除して"},
            now=ctx.clock.now(),
        )
    mismatch_context = _context(
        ctx,
        account,
        session_id,
        turn.id,
        (ToolProvenanceRef(source=ToolProvenance.USER_INPUT, item_id=mismatch.id),),
    )
    assert (
        await _error(
            ctx,
            "delete_long_term_memory",
            mismatch_context,
            {"memory_id": saved.memory_id},
        )
        == "MEMORY_DELETE_NOT_APPROVED"
    )
    assert await _memory_counts(ctx, account.company_id) == (1, 1, 1)
    delete_context = _context(
        ctx,
        account,
        session_id,
        turn.id,
        (ToolProvenanceRef(source=ToolProvenance.USER_INPUT, item_id=forget.id),),
    )
    deleted = await _execute(
        ctx, "delete_long_term_memory", delete_context, {"memory_id": saved.memory_id}
    )
    assert deleted.deleted is True
    assert await _memory_counts(ctx, account.company_id) == (0, 0, 0)
    try:
        await _execute(
            ctx, "delete_long_term_memory", delete_context, {"memory_id": saved.memory_id}
        )
    except ToolDomainError as error:
        assert error.code == "MEMORY_NOT_FOUND"
    else:
        raise AssertionError("deleted memory must not remain")


async def test_get_session_itemsはCheckpoint元だけを会話順で返す(
    account: Account, ctx: ServiceContext
) -> None:
    session_id = await account.create_session()
    async with ctx.session_factory() as session, session.begin():
        locked = await SessionRepository(session).get_parent(
            account.marketer_id, session_id, lock=True
        )
        assert locked is not None
        source_turn = await TurnRepository(session).create_turn(session_id, ctx.clock.now())
        source = await TurnRepository(session).append_item(
            source_turn.id,
            key="source",
            item_type=AgentItemType.USER_MESSAGE,
            source=AgentContentSource.USER_INPUT,
            content={"text": "元の発言"},
            now=ctx.clock.now(),
        )
        await TurnRepository(session).finish_turn(
            source_turn.id, status=AgentTurnStatus.COMPLETED, now=ctx.clock.now()
        )
        await TurnRepository(session).create_checkpoint(
            session_id,
            source_turn.id,
            summary="要約",
            source_item_ids=(source.id,),
            now=ctx.clock.now(),
        )
        current = await TurnRepository(session).create_turn(session_id, ctx.clock.now())
    context = _context(ctx, account, session_id, current.id)
    output = await _execute(ctx, "get_session_items", context, {"item_ids": [source.id]})
    assert output.items[0].item_id == source.id
    assert output.items[0].content == {"text": "元の発言"}


async def test_get_session_itemsは隔離内容を隠し全拒否条件で部分返却しない(
    account: Account, ctx: ServiceContext, new_account: AccountFactory
) -> None:
    session_id = await account.create_session()
    other = await new_account()
    other_session_id = await other.create_session()
    raw_secret = "RAW-QUARANTINED-SECRET"
    override = {"text": "安全な代替内容"}
    async with ctx.session_factory() as session, session.begin():
        turns = TurnRepository(session)
        first = await turns.create_turn(session_id, ctx.clock.now())
        active = await turns.append_item(
            first.id,
            key="active-source",
            item_type=AgentItemType.USER_MESSAGE,
            source=AgentContentSource.USER_INPUT,
            content={"text": "active"},
            now=ctx.clock.now(),
        )
        quarantined = await turns.append_item(
            first.id,
            key="quarantined-source",
            item_type=AgentItemType.ASSISTANT_MESSAGE,
            source=AgentContentSource.AGENT_OUTPUT,
            content={"text": raw_secret},
            now=ctx.clock.now(),
        )
        await turns.finish_turn(first.id, status=AgentTurnStatus.COMPLETED, now=ctx.clock.now())
        assert await turns.quarantine_item(
            quarantined.id,
            reason="test",
            context_override=override,
            now=ctx.clock.now(),
        )

        unfinished_turn = await turns.create_turn(session_id, ctx.clock.now())
        unfinished = await turns.append_item(
            unfinished_turn.id,
            key="unfinished-source",
            item_type=AgentItemType.USER_MESSAGE,
            source=AgentContentSource.USER_INPUT,
            content={"text": "unfinished"},
            now=ctx.clock.now(),
        )
        await turns.finish_turn(
            unfinished_turn.id, status=AgentTurnStatus.COMPLETED, now=ctx.clock.now()
        )
        await turns.create_checkpoint(
            session_id,
            unfinished_turn.id,
            summary="要約",
            source_item_ids=(active.id, quarantined.id, unfinished.id),
            now=ctx.clock.now(),
        )
        await session.execute(
            update(AgentTurn)
            .where(AgentTurn.id == unfinished_turn.id)
            .values(status=AgentTurnStatus.RUNNING, completed_at=None)
        )

        outside_turn = await turns.create_turn(session_id, ctx.clock.now())
        outside = await turns.append_item(
            outside_turn.id,
            key="outside-source",
            item_type=AgentItemType.USER_MESSAGE,
            source=AgentContentSource.USER_INPUT,
            content={"text": "outside"},
            now=ctx.clock.now(),
        )
        await turns.finish_turn(
            outside_turn.id, status=AgentTurnStatus.COMPLETED, now=ctx.clock.now()
        )
        current = await turns.create_turn(session_id, ctx.clock.now())

        other_turn = await turns.create_turn(other_session_id, ctx.clock.now())
        other_item = await turns.append_item(
            other_turn.id,
            key="other-source",
            item_type=AgentItemType.USER_MESSAGE,
            source=AgentContentSource.USER_INPUT,
            content={"text": "other"},
            now=ctx.clock.now(),
        )
        await turns.finish_turn(
            other_turn.id, status=AgentTurnStatus.COMPLETED, now=ctx.clock.now()
        )

    context = _context(ctx, account, session_id, current.id)
    output = await _execute(
        ctx,
        "get_session_items",
        context,
        {"item_ids": [active.id, quarantined.id]},
    )
    assert [item.item_id for item in output.items] == [active.id, quarantined.id]
    assert output.items[1].content == override
    assert raw_secret not in repr(output.model_dump())

    for invalid_id in (outside.id, other_item.id, unfinished.id, 9_999_999_999):
        assert (
            await _error(
                ctx,
                "get_session_items",
                context,
                {"item_ids": [active.id, invalid_id]},
            )
            == "ITEM_NOT_FOUND"
        )

    ctx.settings.tool_session_item_limit = 1
    assert (
        await _error(
            ctx,
            "get_session_items",
            context,
            {"item_ids": [active.id, quarantined.id]},
        )
        == "INVALID_ARGUMENT"
    )
    ctx.settings.tool_session_item_limit = 20
    ctx.settings.tool_session_output_max_bytes = 1
    assert (
        await _error(ctx, "get_session_items", context, {"item_ids": [active.id]})
        == "INVALID_ARGUMENT"
    )


async def test_業務Toolは別会社IDをnot_foundとして扱い検索から除外する(
    account: Account,
    new_account: AccountFactory,
    ctx: ServiceContext,
) -> None:
    other = await new_account()
    own_session = await account.create_session()
    own_campaign = await account.create_campaign(own_session, title="自社施策")
    own_response = await account.publish_post(own_session, post_body(own_campaign, body="自社投稿"))
    own_post = int(own_response.json()["data"]["post_id"])
    own_memory = await insert_memory(account.company_id, "自社だけの記憶")

    other_session = await other.create_session()
    other_campaign = await other.create_campaign(other_session, title="他社施策")
    other_response = await other.publish_post(
        other_session, post_body(other_campaign, body="他社投稿")
    )
    other_post = int(other_response.json()["data"]["post_id"])
    other_memory = await insert_memory(other.company_id, "他社だけの記憶")

    turn_id, source_id = await _new_turn(ctx, account, own_session)
    provenance = (ToolProvenanceRef(source=ToolProvenance.USER_INPUT, item_id=source_id),)
    context = _context(ctx, account, own_session, turn_id, provenance)

    assert (
        await _error(ctx, "get_campaign", context, {"campaign_id": other_campaign})
        == "CAMPAIGN_NOT_FOUND"
    )
    assert await _error(ctx, "get_post", context, {"post_id": other_post}) == "POST_NOT_FOUND"
    assert (
        await _error(ctx, "get_marketing_metrics", context, {"campaign_id": other_campaign})
        == "METRICS_NOT_FOUND"
    )
    assert (
        await _error(ctx, "get_marketing_metrics", context, {"post_id": other_post})
        == "METRICS_NOT_FOUND"
    )
    assert (
        await _error(
            ctx,
            "search_posts",
            context,
            {"query": "他社投稿", "campaign_id": other_campaign, "limit": 20},
        )
        == "CAMPAIGN_NOT_FOUND"
    )
    assert (
        await _error(ctx, "delete_long_term_memory", context, {"memory_id": other_memory})
        == "MEMORY_NOT_FOUND"
    )

    campaign_search = await _execute(
        ctx, "search_campaigns", context, {"query": "他社施策", "limit": 20}
    )
    post_search = await _execute(ctx, "search_posts", context, {"query": "他社投稿", "limit": 20})
    memory_search = await _execute(
        ctx, "search_long_term_memory", context, {"query": "他社だけの記憶", "limit": 20}
    )
    assert own_campaign in {item.campaign_id for item in campaign_search.campaigns}
    assert other_campaign not in {item.campaign_id for item in campaign_search.campaigns}
    assert own_post in {item.post_id for item in post_search.posts}
    assert other_post not in {item.post_id for item in post_search.posts}
    assert own_memory in {item.memory_id for item in memory_search.memories}
    assert other_memory not in {item.memory_id for item in memory_search.memories}

    before = await _memory_counts(ctx, account.company_id)
    for relations in (
        {"campaign_ids": [other_campaign], "post_ids": []},
        {"campaign_ids": [], "post_ids": [other_post]},
    ):
        assert (
            await _error(
                ctx,
                "save_long_term_memory",
                context,
                {
                    "source_item_id": source_id,
                    "content": "保存されない内容",
                    **relations,
                },
            )
            == "RELATED_ENTITY_NOT_FOUND"
        )
    assert await _memory_counts(ctx, account.company_id) == before


async def test_Memory保存は失敗時rollbackしmask済みEmbeddingと関連境界を守る(
    account: Account,
    ctx: ServiceContext,
    embedding: FakeEmbedding,
    clock: FixedClock,
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id, title="Archive関連先")
    response = await account.publish_post(session_id, post_body(campaign_id, body="関連投稿"))
    assert response.status_code == 201, response.text
    post_id = int(response.json()["data"]["post_id"])
    await archive_campaign(campaign_id, clock.now())
    turn_id, source_id = await _new_turn(ctx, account, session_id)
    context = _context(
        ctx,
        account,
        session_id,
        turn_id,
        (ToolProvenanceRef(source=ToolProvenance.USER_INPUT, item_id=source_id),),
    )
    assert await _memory_counts(ctx, account.company_id) == (0, 0, 0)

    assert (
        await _error(
            ctx,
            "save_long_term_memory",
            context,
            {
                "source_item_id": source_id,
                "content": "不正関連先",
                "campaign_ids": [9_999_999_999],
                "post_ids": [],
            },
        )
        == "RELATED_ENTITY_NOT_FOUND"
    )
    assert await _memory_counts(ctx, account.company_id) == (0, 0, 0)

    embedding.fail = True
    assert (
        await _error(
            ctx,
            "save_long_term_memory",
            context,
            {
                "source_item_id": source_id,
                "content": "Embedding失敗",
                "campaign_ids": [],
                "post_ids": [],
            },
        )
        == "EMBEDDING_FAILED"
    )
    embedding.fail = False
    assert await _memory_counts(ctx, account.company_id) == (0, 0, 0)

    saved = await _execute(
        ctx,
        "save_long_term_memory",
        context,
        {
            "source_item_id": source_id,
            "content": "連絡先 user@example.com を保存",
            "campaign_ids": [campaign_id],
            "post_ids": [post_id],
        },
    )
    assert embedding.calls[-1] == "連絡先 [EMAIL] を保存"
    assert await _memory_counts(ctx, account.company_id) == (1, 1, 1)

    await _set_publication(ctx, post_id, ApiIdempotencyStatus.PROCESSING)
    assert (
        await _error(
            ctx,
            "save_long_term_memory",
            context,
            {
                "source_item_id": source_id,
                "content": "非公開投稿関連",
                "campaign_ids": [],
                "post_ids": [post_id],
            },
        )
        == "RELATED_ENTITY_NOT_FOUND"
    )
    assert await _memory_counts(ctx, account.company_id) == (1, 1, 1)
    assert saved.memory_id > 0


@pytest.mark.parametrize(
    "status",
    [
        ApiIdempotencyStatus.PROCESSING,
        ApiIdempotencyStatus.FAILED,
        ApiIdempotencyStatus.OUTCOME_UNKNOWN,
    ],
)
async def test_Post_Toolは公開成功以外をnot_foundとして検索から除外する(
    account: Account,
    ctx: ServiceContext,
    status: ApiIdempotencyStatus,
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    visible_response = await account.publish_post(
        session_id, post_body(campaign_id, body="公開成功投稿")
    )
    hidden_response = await account.publish_post(
        session_id, post_body(campaign_id, body=f"非公開状態 {status.value}")
    )
    visible_id = int(visible_response.json()["data"]["post_id"])
    hidden_id = int(hidden_response.json()["data"]["post_id"])
    await _set_publication(ctx, hidden_id, status)
    turn_id, _ = await _new_turn(ctx, account, session_id)
    context = _context(ctx, account, session_id, turn_id)

    assert await _error(ctx, "get_post", context, {"post_id": hidden_id}) == "POST_NOT_FOUND"
    assert (
        await _error(ctx, "get_marketing_metrics", context, {"post_id": hidden_id})
        == "METRICS_NOT_FOUND"
    )
    searched = await _execute(ctx, "search_posts", context, {"query": "非公開状態", "limit": 20})
    ids = {item.post_id for item in searched.posts}
    assert hidden_id not in ids
    assert visible_id in ids


async def test_failed_Metricsは部分値をPostとMetrics出力へ公開しない(
    account: Account, ctx: ServiceContext, clock: FixedClock, embedding: FakeEmbedding
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    response = await account.publish_post(session_id, post_body(campaign_id, body="計測失敗投稿"))
    post_id = int(response.json()["data"]["post_id"])
    async with ctx.session_factory() as session, session.begin():
        await session.execute(
            update(PostMetric)
            .where(PostMetric.post_id == post_id)
            .values(
                status=PostMetricStatus.FAILED,
                x_pv_count=999,
                landing_user_count=99,
                measured_at=clock.now(),
            )
        )
    turn_id, _ = await _new_turn(ctx, account, session_id)
    context = _context(ctx, account, session_id, turn_id)
    calls_before_get = len(embedding.calls)

    post = await _execute(ctx, "get_post", context, {"post_id": post_id})
    metrics = await _execute(ctx, "get_marketing_metrics", context, {"post_id": post_id})
    campaign = await _execute(ctx, "get_marketing_metrics", context, {"campaign_id": campaign_id})
    assert len(embedding.calls) == calls_before_get
    assert post.post.metrics.status == PostMetricStatus.FAILED
    assert post.post.metrics.x_pv_count is None
    assert post.post.metrics.landing_user_count is None
    assert post.post.metrics.measured_at is None
    assert metrics.metrics.status == PostMetricStatus.FAILED
    assert metrics.metrics.x_pv_count is None
    assert metrics.metrics.landing_user_count is None
    assert metrics.metrics.measured_at is None
    assert campaign.summary.post_count == 1
    assert campaign.summary.failed_count == 1
    assert campaign.summary.x_pv_count == 0

    searched = await _execute(ctx, "search_posts", context, {"query": "計測失敗投稿", "limit": 20})
    found = next(item for item in searched.posts if item.post_id == post_id)
    assert found.metrics.status == PostMetricStatus.FAILED
    assert found.metrics.x_pv_count is None
    assert found.metrics.landing_user_count is None
    assert found.metrics.measured_at is None


async def test_Business_schema不正はExecutorでINVALID_ARGUMENTを返す(
    account: Account, ctx: ServiceContext
) -> None:
    session_id = await account.create_session()
    turn_id, _ = await _new_turn(ctx, account, session_id)
    executor = ToolExecutor(
        ctx,
        marketer_id=account.marketer_id,
        company_id=account.company_id,
        session_id=session_id,
        turn_id=turn_id,
        reporter=NullReporter(),
    )
    result = await executor.invoke(
        ToolCall(
            name="get_campaign",
            stable_key="invalid-business-schema",
            arguments={"campaign_id": "1"},
        )
    )
    assert result.error is not None
    assert result.error.code == "INVALID_ARGUMENT"
    assert result.error.retryable is False
