import asyncio
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from agent_runtime.model import (
    FinalAnswer,
    GuardrailBlocked,
    ModelDecision,
    ModelRequest,
    ModelResult,
)
from agent_runtime.real_runner import RealAgentRunner
from domain.enums import (
    AgentContentSource,
    AgentItemType,
    AgentTurnStatus,
    AgentType,
    ApiIdempotencyStatus,
    ApiOperation,
    ToolExecutionStatus,
)
from models import (
    AgentItem,
    AgentSession,
    AgentTurn,
    ApiIdempotencyRequest,
    LlmCall,
    SecurityEvent,
    ToolExecution,
)
from repositories.agent import (
    LlmCallRepository,
    SessionRepository,
    ToolExecutionRepository,
    TurnNotRunningError,
    TurnRepository,
)
from services.context import ServiceContext
from services.turn_recovery import TurnRecoveryService
from tests.support.client import Account
from tests.support.fakes import FakeAgentRunner, FixedClock


async def test_global復旧は未訪問parent_childを取消しapprovalを除外する(
    account: Account, ctx: ServiceContext, clock: FixedClock
) -> None:
    parent_id = await account.create_session()
    now = clock.now()
    async with ctx.session_factory() as session, session.begin():
        assert await SessionRepository(session).get_parent(
            account.marketer_id, parent_id, lock=True
        )
        parent_turn = await TurnRepository(session).create_turn(parent_id, now)
        await TurnRepository(session).append_item(
            parent_turn.id,
            key="parent-input",
            item_type=AgentItemType.USER_MESSAGE,
            source=AgentContentSource.USER_INPUT,
            content={"text": "stale parent"},
            now=now,
        )
        child = AgentSession(
            marketer_id=account.marketer_id,
            parent_session_id=parent_id,
            agent=AgentType.CAMPAIGN_PLANNER,
            created_at=now,
            updated_at=now,
        )
        session.add(child)
        await session.flush()
        child_turn = await TurnRepository(session).create_turn(child.id, now)
        tool_call = await TurnRepository(session).append_item(
            child_turn.id,
            key="child-tool",
            item_type=AgentItemType.TOOL_CALL,
            source=AgentContentSource.AGENT_OUTPUT,
            content={"name": "get_campaign", "call_key": "child", "arguments": {}},
            now=now,
        )
        execution = ToolExecution(
            tool_call_item_id=tool_call.id,
            status=ToolExecutionStatus.RUNNING,
            attempt_count=1,
            created_at=now,
        )
        session.add(execution)
        approval_turn = await TurnRepository(session).create_turn(parent_id, now)
        approval = ApiIdempotencyRequest(
            marketer_id=account.marketer_id,
            session_id=parent_id,
            agent_turn_id=approval_turn.id,
            operation=ApiOperation.UPSERT_CAMPAIGN,
            idempotency_key=uuid.uuid4(),
            request_hash="a" * 64,
            status=ApiIdempotencyStatus.PROCESSING,
            execution_token=uuid.uuid4(),
            lease_expires_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(approval)

    clock.advance(331)
    recovered = await TurnRecoveryService(ctx).recover_all()
    repeated = await TurnRecoveryService(ctx).recover_all()

    assert {parent_turn.id, child_turn.id}.issubset(recovered)
    assert repeated == []
    async with ctx.session_factory() as session:
        parent = await session.get(AgentTurn, parent_turn.id)
        child_row = await session.get(AgentTurn, child_turn.id)
        approval_row = await session.get(AgentTurn, approval_turn.id)
        execution_row = await session.get(ToolExecution, execution.id)
    assert parent is not None and parent.error_code == "TURN_INTERRUPTED"
    assert child_row is not None and child_row.error_code == "TURN_INTERRUPTED"
    assert approval_row is not None and approval_row.status == AgentTurnStatus.RUNNING
    assert execution_row is not None
    assert execution_row.status == ToolExecutionStatus.CANCELLED
    assert execution_row.completed_at == clock.now()

    async with ctx.session_factory() as session, session.begin():
        turns = TurnRepository(session)
        with pytest.raises(TurnNotRunningError):
            await turns.append_item(
                parent_turn.id,
                key="late-item",
                item_type=AgentItemType.ASSISTANT_MESSAGE,
                source=AgentContentSource.AGENT_OUTPUT,
                content={"text": "late"},
                now=clock.now(),
            )
        assert (
            await LlmCallRepository(session).create_if_running(
                parent_turn.id,
                request_id=f"late-{uuid.uuid4().hex}",
                input_tokens=1,
                output_tokens=1,
                cost_usd=Decimal("0.01"),
                response_time_ms=1,
                succeeded=True,
                error_code=None,
            )
            is None
        )
        assert (
            await ToolExecutionRepository(session).prepare(
                turn_id=parent_turn.id,
                stable_key="late-tool",
                name="get_campaign",
                arguments={"campaign_id": 1},
                provenance=[],
                now=clock.now(),
            )
            is None
        )
    async with ctx.session_factory() as session:
        late_items = await session.scalar(
            select(AgentItem.id).where(
                AgentItem.agent_turn_id == parent_turn.id,
                AgentItem.idempotency_key == "late-item",
            )
        )
        late_calls = await session.scalar(
            select(LlmCall.id).where(LlmCall.agent_turn_id == parent_turn.id)
        )
    assert late_items is None
    assert late_calls is None


async def test_global復旧がLLM応答より先なら遅延応答を保存しない(
    account: Account, ctx: ServiceContext, clock: FixedClock
) -> None:
    class _BlockingModel:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.gate = asyncio.Event()

        async def complete(self, request: ModelRequest) -> ModelResult:
            del request
            self.started.set()
            await self.gate.wait()
            return ModelResult(
                decision=ModelDecision(final=FinalAnswer(content="late reply")),
                request_id=f"late-reply-{uuid.uuid4().hex}",
                prompt_tokens=1,
                completion_tokens=1,
                cost_usd=Decimal("0.01"),
                latency_ms=1,
            )

    parent_id = await account.create_session()
    model = _BlockingModel()
    object.__setattr__(ctx, "agent_runner", RealAgentRunner(ctx, model))
    task = asyncio.create_task(
        account.client.post(f"/api/v1/agent-sessions/{parent_id}/turns", json={"message": "wait"})
    )
    await asyncio.wait_for(model.started.wait(), 5)
    clock.advance(331)

    recovered = await TurnRecoveryService(ctx).recover_all()
    model.gate.set()
    response = await task

    assert len(recovered) == 1
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "TURN_INTERRUPTED"
    turn_id = response.json()["error"]["agent_turn_id"]
    async with ctx.session_factory() as session:
        items = list(
            (
                await session.execute(select(AgentItem).where(AgentItem.agent_turn_id == turn_id))
            ).scalars()
        )
        calls = list(
            (
                await session.execute(select(LlmCall).where(LlmCall.agent_turn_id == turn_id))
            ).scalars()
        )
    assert [item.item_type for item in items] == [AgentItemType.USER_MESSAGE]
    assert calls == []


async def test_global復旧後の遅延guardrailは監査eventを追加しない(
    account: Account, ctx: ServiceContext, clock: FixedClock
) -> None:
    class _BlockingGuardrailModel:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.gate = asyncio.Event()

        async def complete(self, request: ModelRequest) -> ModelResult:
            del request
            self.started.set()
            await self.gate.wait()
            raise GuardrailBlocked(request_id=f"late-guardrail-{uuid.uuid4().hex}")

    parent_id = await account.create_session()
    model = _BlockingGuardrailModel()
    object.__setattr__(ctx, "agent_runner", RealAgentRunner(ctx, model))
    task = asyncio.create_task(
        account.client.post(f"/api/v1/agent-sessions/{parent_id}/turns", json={"message": "wait"})
    )
    await asyncio.wait_for(model.started.wait(), 5)
    clock.advance(331)

    await TurnRecoveryService(ctx).recover_all()
    model.gate.set()
    response = await task

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "TURN_INTERRUPTED"
    turn_id = response.json()["error"]["agent_turn_id"]
    async with ctx.session_factory() as session:
        event = await session.scalar(
            select(SecurityEvent.id).where(SecurityEvent.agent_turn_id == turn_id)
        )
        call = await session.scalar(select(LlmCall.id).where(LlmCall.agent_turn_id == turn_id))
    assert event is None
    assert call is None


async def test_chat実行中でもapproval_turnは独立して完了できる(
    account: Account, agent: FakeAgentRunner
) -> None:
    parent_id = await account.create_session()
    agent.gate = asyncio.Event()
    chat = asyncio.create_task(
        account.client.post(f"/api/v1/agent-sessions/{parent_id}/turns", json={"message": "wait"})
    )
    await asyncio.wait_for(agent.started.wait(), 5)

    campaign_id = await account.create_campaign(parent_id)
    agent.gate.set()
    chat_response = await chat

    assert campaign_id > 0
    assert chat_response.status_code == 201
