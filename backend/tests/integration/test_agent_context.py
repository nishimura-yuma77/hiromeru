import uuid
from datetime import datetime

import pytest
from sqlalchemy import func, select, update

from domain.enums import (
    AgentContentSource,
    AgentItemType,
    AgentTurnStatus,
    AgentType,
    SecurityDetector,
    SecurityEnforcement,
    SecurityEventType,
)
from models import (
    AgentContextCheckpoint,
    AgentContextCheckpointItem,
    AgentItem,
    AgentSession,
    AgentTurn,
    SecurityEvent,
)
from repositories.agent import InvalidCheckpointSourcesError, TurnRepository
from repositories.database import SessionLocal
from services.agent_context import AgentContextBuilder
from services.context import ServiceContext
from tests.conftest import AccountFactory
from tests.support.client import Account
from tests.support.fakes import FakeAgentRunner, FakeContextCompactor, FixedClock


async def _completed_turn(session_id: int, text: str, now: datetime) -> tuple[int, tuple[int, ...]]:
    async with SessionLocal() as session, session.begin():
        turns = TurnRepository(session)
        turn = await turns.create_turn(session_id, now)
        user = await turns.append_item(
            turn.id,
            key="user",
            item_type=AgentItemType.USER_MESSAGE,
            source=AgentContentSource.USER_INPUT,
            content={"text": text},
            now=now,
        )
        assistant = await turns.append_item(
            turn.id,
            key="assistant",
            item_type=AgentItemType.ASSISTANT_MESSAGE,
            source=AgentContentSource.AGENT_OUTPUT,
            content={"text": f"reply:{text}"},
            now=now,
        )
        await turns.finish_turn(turn.id, status=AgentTurnStatus.COMPLETED, now=now)
        return turn.id, (user.id, assistant.id)


async def _turn_with_status(
    session_id: int, status: AgentTurnStatus, text: str, now: datetime
) -> tuple[int, int]:
    async with SessionLocal() as session, session.begin():
        turns = TurnRepository(session)
        turn = await turns.create_turn(session_id, now)
        item = await turns.append_item(
            turn.id,
            key="user",
            item_type=AgentItemType.USER_MESSAGE,
            source=AgentContentSource.USER_INPUT,
            content={"text": text},
            now=now,
        )
        if status != AgentTurnStatus.RUNNING:
            await turns.finish_turn(turn.id, status=status, now=now)
        return turn.id, item.id


async def _send(account: Account, session_id: int, message: str):
    return await account.client.post(
        f"/api/v1/agent-sessions/{session_id}/turns", json={"message": message}
    )


async def test_ContextはChatとApprovalを完了Turn順に並べ現在入力を一度だけ含む(
    account: Account, agent: FakeAgentRunner
) -> None:
    session_id = await account.create_session()
    await _send(account, session_id, "chat-1")
    await account.create_campaign(session_id)

    response = await _send(account, session_id, "chat-2")

    assert response.status_code == 201
    entries = agent.inputs[-1].context.entries
    assert [entry.item_type for entry in entries] == [
        "user_message",
        "assistant_message",
        "user_message",
        "assistant_message",
        "user_message",
    ]
    assert entries[-1].content == {"text": "chat-2"}
    assert sum(entry.content == {"text": "chat-2"} for entry in entries) == 1
    assert entries[3].content["kind"] == "api_result"


async def test_Contextは非completed履歴を除外する(
    account: Account, ctx: ServiceContext, clock: FixedClock
) -> None:
    session_id = await account.create_session()
    for status in (
        AgentTurnStatus.FAILED,
        AgentTurnStatus.BLOCKED,
        AgentTurnStatus.CANCELLED,
        AgentTurnStatus.PENDING,
    ):
        turn_id, _ = await _turn_with_status(session_id, status, status.value, clock.now())
        if status == AgentTurnStatus.PENDING:
            async with SessionLocal() as session, session.begin():
                await session.execute(
                    update(AgentTurn)
                    .where(AgentTurn.id == turn_id)
                    .values(status=AgentTurnStatus.PENDING)
                )
    current_id, _ = await _turn_with_status(
        session_id, AgentTurnStatus.RUNNING, "current", clock.now()
    )

    context = await AgentContextBuilder(ctx).build(session_id, current_id)

    assert [entry.content for entry in context.entries if entry.kind == "item"] == [
        {"text": "current"}
    ]


async def test_Contextは現在Turnより後に完了したTurnを先取りしない(
    account: Account, ctx: ServiceContext, clock: FixedClock
) -> None:
    session_id = await account.create_session()
    await _completed_turn(session_id, "before", clock.now())
    current_id, _ = await _turn_with_status(
        session_id, AgentTurnStatus.RUNNING, "current", clock.now()
    )
    await _completed_turn(session_id, "after", clock.now())

    context = await AgentContextBuilder(ctx).build(session_id, current_id)

    contents = [entry.content for entry in context.entries if entry.kind == "item"]
    assert {"text": "before"} in contents
    assert {"text": "current"} in contents
    assert {"text": "after"} not in contents


async def test_隔離ItemはoverrideだけをContextへ渡し関連Checkpointを無効化する(
    account: Account, ctx: ServiceContext, clock: FixedClock
) -> None:
    session_id = await account.create_session()
    turn_id, item_ids = await _completed_turn(session_id, "RAW-SECRET", clock.now())
    async with SessionLocal() as session, session.begin():
        repository = TurnRepository(session)
        checkpoint = await repository.create_checkpoint(
            session_id,
            turn_id,
            summary="unsafe old summary",
            source_item_ids=item_ids,
            now=clock.now(),
        )
        assert await repository.quarantine_item(
            item_ids[0],
            reason="prompt_injection",
            context_override={"notice": "sanitized"},
            now=clock.now(),
        )
        checkpoint_id = checkpoint.id
    current_id, _ = await _turn_with_status(
        session_id, AgentTurnStatus.RUNNING, "current", clock.now()
    )

    context = await AgentContextBuilder(ctx).build(session_id, current_id)

    quarantined_entry = next(entry for entry in context.entries if entry.item_id == item_ids[0])
    assert quarantined_entry.content == {"notice": "sanitized"}
    assert "RAW-SECRET" not in str(quarantined_entry)
    assert "unsafe old summary" not in str(context.entries)
    async with SessionLocal() as session:
        checkpoint = await session.get(AgentContextCheckpoint, checkpoint_id)
        item = await session.get(AgentItem, item_ids[0])
        assert checkpoint is not None and checkpoint.invalidated_at == clock.now()
        assert item is not None and item.content == {"text": "RAW-SECRET"}


async def test_Security通知は直近5履歴Turnからallowlist項目だけを導出する(
    account: Account, ctx: ServiceContext, clock: FixedClock
) -> None:
    session_id = await account.create_session()
    statuses = [
        AgentTurnStatus.COMPLETED,
        AgentTurnStatus.FAILED,
        AgentTurnStatus.BLOCKED,
        AgentTurnStatus.COMPLETED,
        AgentTurnStatus.FAILED,
        AgentTurnStatus.COMPLETED,
    ]
    turn_ids: list[int] = []
    async with SessionLocal() as session, session.begin():
        turns = TurnRepository(session)
        for number, status in enumerate(statuses):
            turn = await turns.create_turn(session_id, clock.now())
            item = await turns.append_item(
                turn.id,
                key="user",
                item_type=AgentItemType.USER_MESSAGE,
                source=AgentContentSource.USER_INPUT,
                content={"text": f"history-{number}"},
                now=clock.now(),
            )
            await turns.finish_turn(turn.id, status=status, now=clock.now())
            turn_ids.append(turn.id)
            session.add(
                SecurityEvent(
                    agent_turn_id=turn.id,
                    agent_item_id=item.id,
                    event_type=SecurityEventType.PROMPT_INJECTION,
                    detector=SecurityDetector.APPLICATION,
                    source=AgentContentSource.USER_INPUT,
                    enforcement=SecurityEnforcement.BLOCKED,
                    external_event_id=f"external-{uuid.uuid4()}-{number}",
                    summary=f"private-{number}",
                    event_metadata={"raw": f"secret-{number}"},
                    detected_at=clock.now(),
                )
            )
    current_id, _ = await _turn_with_status(
        session_id, AgentTurnStatus.RUNNING, "current", clock.now()
    )

    context = await AgentContextBuilder(ctx).build(session_id, current_id)

    notices = [entry for entry in context.entries if entry.kind == "security_notice"]
    assert len(notices) == 5
    assert all(
        notice.content == {"event_type": "prompt_injection", "enforcement": "blocked"}
        for notice in notices
    )
    assert "private-" not in str(notices)
    assert "secret-" not in str(notices)
    assert "external-" not in str(notices)
    assert turn_ids[0] not in [notice.turn_id for notice in notices]


async def test_圧縮成功時はCheckpointと全sourceを保存し直近Turnを原文保持する(
    account: Account,
    agent: FakeAgentRunner,
    compactor: FakeContextCompactor,
    ctx: ServiceContext,
) -> None:
    session_id = await account.create_session()
    await _send(account, session_id, "oldest")
    await _send(account, session_id, "latest-raw")
    ctx.settings.agent_context_compaction_threshold_bytes = 1
    ctx.settings.agent_context_hard_limit_bytes = 100_000
    compactor.summary = "summary-v1"

    response = await _send(account, session_id, "current")

    assert response.status_code == 201
    entries = agent.inputs[-1].context.entries
    assert entries[0].kind == "checkpoint"
    assert entries[0].content == {"summary": "summary-v1"}
    assert any(entry.content == {"text": "latest-raw"} for entry in entries)
    assert not any(entry.content == {"text": "oldest"} for entry in entries)
    async with SessionLocal() as session:
        checkpoint_count = await session.scalar(
            select(func.count(AgentContextCheckpoint.id)).where(
                AgentContextCheckpoint.session_id == session_id
            )
        )
        source_count = await session.scalar(
            select(func.count(AgentContextCheckpointItem.item_id))
            .join(
                AgentContextCheckpoint,
                AgentContextCheckpoint.id == AgentContextCheckpointItem.checkpoint_id,
            )
            .where(AgentContextCheckpoint.session_id == session_id)
        )
    assert checkpoint_count == 1
    assert source_count == 2

    compactor.summary = "summary-v2"
    second_response = await _send(account, session_id, "next-current")

    assert second_response.status_code == 201
    assert compactor.inputs[-1][0].kind == "checkpoint"
    assert compactor.inputs[-1][0].content == {"summary": "summary-v1"}
    async with SessionLocal() as session:
        latest_checkpoint_id = await session.scalar(
            select(AgentContextCheckpoint.id)
            .where(AgentContextCheckpoint.session_id == session_id)
            .order_by(AgentContextCheckpoint.id.desc())
            .limit(1)
        )
        latest_source_count = await session.scalar(
            select(func.count(AgentContextCheckpointItem.item_id)).where(
                AgentContextCheckpointItem.checkpoint_id == latest_checkpoint_id
            )
        )
    assert latest_source_count == 4


async def test_圧縮失敗でもhard_limit内なら未圧縮でRunnerを継続する(
    account: Account,
    agent: FakeAgentRunner,
    compactor: FakeContextCompactor,
    ctx: ServiceContext,
) -> None:
    session_id = await account.create_session()
    await _send(account, session_id, "old")
    await _send(account, session_id, "recent")
    ctx.settings.agent_context_compaction_threshold_bytes = 1
    ctx.settings.agent_context_hard_limit_bytes = 100_000
    compactor.error = RuntimeError("compact failed")

    response = await _send(account, session_id, "current")

    assert response.status_code == 201
    assert any(entry.content == {"text": "old"} for entry in agent.inputs[-1].context.entries)


async def test_圧縮失敗かつhard_limit超過ならTurnを専用Errorでfailedにする(
    account: Account, compactor: FakeContextCompactor, ctx: ServiceContext
) -> None:
    session_id = await account.create_session()
    await _send(account, session_id, "old")
    await _send(account, session_id, "recent")
    ctx.settings.agent_context_compaction_threshold_bytes = 1
    ctx.settings.agent_context_hard_limit_bytes = 2
    compactor.error = RuntimeError("compact failed")

    response = await _send(account, session_id, "current")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "CONTEXT_COMPACTION_FAILED"


async def test_圧縮後もhard_limit超過ならCheckpointを保存しない(
    account: Account, compactor: FakeContextCompactor, ctx: ServiceContext
) -> None:
    session_id = await account.create_session()
    await _send(account, session_id, "old")
    await _send(account, session_id, "recent")
    ctx.settings.agent_context_compaction_threshold_bytes = 1
    ctx.settings.agent_context_hard_limit_bytes = 500
    compactor.summary = "x" * 1_000

    response = await _send(account, session_id, "current")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "CONTEXT_COMPACTION_FAILED"
    async with SessionLocal() as session:
        count = await session.scalar(
            select(func.count(AgentContextCheckpoint.id)).where(
                AgentContextCheckpoint.session_id == session_id
            )
        )
    assert count == 0


async def test_子Sessionでは閾値超過でもCheckpointを作らない(
    account: Account, ctx: ServiceContext, clock: FixedClock
) -> None:
    parent_id = await account.create_session()
    async with SessionLocal() as session, session.begin():
        child = AgentSession(
            marketer_id=account.marketer_id,
            parent_session_id=parent_id,
            agent=AgentType.CAMPAIGN_PLANNER,
            created_at=clock.now(),
            updated_at=clock.now(),
        )
        session.add(child)
        await session.flush()
        child_id = child.id
    await _completed_turn(child_id, "old", clock.now())
    current_id, _ = await _turn_with_status(
        child_id, AgentTurnStatus.RUNNING, "current", clock.now()
    )
    ctx.settings.agent_context_compaction_threshold_bytes = 1
    ctx.settings.agent_context_hard_limit_bytes = 100_000

    await AgentContextBuilder(ctx).build(child_id, current_id)

    async with SessionLocal() as session:
        count = await session.scalar(
            select(func.count(AgentContextCheckpoint.id)).where(
                AgentContextCheckpoint.session_id == child_id
            )
        )
    assert count == 0


async def test_Checkpoint_sourceは別tenant_session_child_noncompletedを拒否する(
    account: Account,
    new_account: AccountFactory,
    ctx: ServiceContext,
    clock: FixedClock,
) -> None:
    session_id = await account.create_session()
    boundary_id, valid_ids = await _completed_turn(session_id, "valid", clock.now())
    running_id, running_item_id = await _turn_with_status(
        session_id, AgentTurnStatus.RUNNING, "running", clock.now()
    )
    other = AgentSession(
        marketer_id=account.marketer_id,
        parent_session_id=session_id,
        agent=AgentType.CONTENT_CREATOR,
        created_at=clock.now(),
        updated_at=clock.now(),
    )
    async with SessionLocal() as session, session.begin():
        session.add(other)
        await session.flush()
        child_id = other.id
    _, child_ids = await _completed_turn(child_id, "child", clock.now())
    another = await new_account()
    another_session_id = await another.create_session()
    _, other_tenant_ids = await _completed_turn(another_session_id, "other", clock.now())

    for invalid_id in (running_item_id, child_ids[0], other_tenant_ids[0]):
        async with SessionLocal() as session, session.begin():
            with pytest.raises(InvalidCheckpointSourcesError):
                await TurnRepository(session).create_checkpoint(
                    session_id,
                    boundary_id,
                    summary="summary",
                    source_item_ids=(*valid_ids, invalid_id),
                    now=clock.now(),
                )

    async with SessionLocal() as session, session.begin():
        await TurnRepository(session).finish_turn(
            running_id, status=AgentTurnStatus.CANCELLED, now=clock.now()
        )
