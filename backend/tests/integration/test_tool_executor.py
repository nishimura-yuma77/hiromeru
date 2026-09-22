import asyncio
from typing import Any

import pytest
from pydantic import BaseModel
from sqlalchemy import select

from agent_runtime.executor import ToolExecutor
from agent_runtime.firewall import FakeAgentFirewall, FirewallDecision
from agent_runtime.runner import AgentContext, AgentContextEntry
from agent_runtime.tools import (
    StrictToolModel,
    ToolCall,
    ToolDefinition,
    ToolProvenance,
    ToolProvenanceRef,
    TransientToolError,
    TrustedToolContext,
)
from api.sse import NullReporter
from domain.enums import (
    AgentContentSource,
    AgentContextClass,
    AgentItemContextStatus,
    AgentItemType,
    AgentTurnStatus,
    AgentType,
    SecurityDetector,
    SecurityEventType,
    ToolExecutionStatus,
)
from models import AgentItem, SecurityEvent, ToolExecution
from repositories.agent import SessionRepository, TurnRepository
from services.context import ServiceContext
from tests.support.client import Account


class Input(StrictToolModel):
    text: str


class Output(StrictToolModel):
    value: str


class RecordingHandler:
    def __init__(self) -> None:
        self.authorized = True
        self.calls = 0
        self.authorize_calls = 0
        self.transient_failures = 0
        self.error: Exception | None = None
        self.output: Any = Output(value="safe")
        self.started = asyncio.Event()
        self.gate: asyncio.Event | None = None

    async def authorize(self, context: TrustedToolContext, tool_input: BaseModel) -> bool:
        self.authorize_calls += 1
        assert context.company_id > 0
        return self.authorized

    async def execute(self, context: TrustedToolContext, tool_input: BaseModel) -> Any:
        self.calls += 1
        self.started.set()
        if self.gate is not None:
            await self.gate.wait()
        if self.calls <= self.transient_failures:
            raise TransientToolError
        if self.error is not None:
            raise self.error
        return self.output


async def _executor(
    account: Account,
    ctx: ServiceContext,
    handler: RecordingHandler | None = None,
    *,
    source: AgentContentSource = AgentContentSource.DATABASE,
    context_class: AgentContextClass = AgentContextClass.CONVERSATION,
    agent_context: AgentContext | None = None,
) -> tuple[ToolExecutor, int, RecordingHandler]:
    session_id = await account.create_session()
    async with ctx.session_factory() as session, session.begin():
        locked = await SessionRepository(session).get_parent(
            account.marketer_id, session_id, lock=True
        )
        assert locked is not None
        turn = await TurnRepository(session).create_turn(session_id, ctx.clock.now())
    selected = handler or RecordingHandler()
    ctx.tool_registry.register(
        ToolDefinition(
            name="sample_tool",
            input_model=Input,
            output_model=Output,
            handler=selected,
            allowed_agents=frozenset({AgentType.PARENT}),
            result_source=source,
            result_context_class=context_class,
        )
    )
    return (
        ToolExecutor(
            ctx,
            marketer_id=account.marketer_id,
            company_id=account.company_id,
            session_id=session_id,
            turn_id=turn.id,
            reporter=NullReporter(),
            agent_context=agent_context,
        ),
        turn.id,
        selected,
    )


async def _rows(
    ctx: ServiceContext, turn_id: int
) -> tuple[list[AgentItem], ToolExecution, list[SecurityEvent]]:
    async with ctx.session_factory() as session:
        items = list(
            (
                await session.execute(
                    select(AgentItem)
                    .where(AgentItem.agent_turn_id == turn_id)
                    .order_by(AgentItem.item_number)
                )
            ).scalars()
        )
        execution = (
            await session.execute(
                select(ToolExecution).where(
                    ToolExecution.tool_call_item_id.in_([item.id for item in items])
                )
            )
        ).scalar_one()
        events = list(
            (
                await session.execute(
                    select(SecurityEvent).where(SecurityEvent.agent_turn_id == turn_id)
                )
            ).scalars()
        )
    return items, execution, events


async def test_成功を同一Turnへ保存し重複invokeでは副作用を再実行しない(
    account: Account, ctx: ServiceContext
) -> None:
    executor, turn_id, handler = await _executor(account, ctx)
    call = ToolCall(
        name="sample_tool",
        stable_key="provider-call-1",
        arguments={"text": "mail user@example.com"},
    )

    first = await executor.invoke(call)
    second = await executor.invoke(call)
    items, execution, events = await _rows(ctx, turn_id)

    assert first == second
    assert handler.calls == 1
    assert [item.item_type for item in items] == [
        AgentItemType.TOOL_CALL,
        AgentItemType.TOOL_RESULT,
    ]
    assert items[0].content == {
        "name": "sample_tool",
        "call_key": "provider-call-1",
        "arguments": {"text": "mail [EMAIL]"},
    }
    assert items[1].related_tool_call_item_id == items[0].id
    assert execution.tool_call_item_id == items[0].id
    assert execution.status == ToolExecutionStatus.COMPLETED
    assert execution.attempt_count == 1
    assert events == []


async def test_同じ引数でもstable_keyが異なれば別実行(
    account: Account, ctx: ServiceContext
) -> None:
    executor, turn_id, handler = await _executor(account, ctx)
    await executor.invoke(
        ToolCall(name="sample_tool", stable_key="call-1", arguments={"text": "x"})
    )
    await executor.invoke(
        ToolCall(name="sample_tool", stable_key="call-2", arguments={"text": "x"})
    )

    async with ctx.session_factory() as session:
        calls = list(
            (
                await session.execute(
                    select(AgentItem).where(
                        AgentItem.agent_turn_id == turn_id,
                        AgentItem.item_type == AgentItemType.TOOL_CALL,
                    )
                )
            ).scalars()
        )
    assert handler.calls == 2
    assert len(calls) == 2


async def test_同じstable_keyを異なるCallへ再利用すると実行しない(
    account: Account, ctx: ServiceContext
) -> None:
    executor, _, handler = await _executor(account, ctx)
    first = ToolCall(name="sample_tool", stable_key="reused", arguments={"text": "first"})
    await executor.invoke(first)

    changed = await executor.invoke(
        ToolCall(name="sample_tool", stable_key="reused", arguments={"text": "second"})
    )

    assert changed.error is not None and changed.error.code == "TOOL_CALL_CONFLICT"
    assert handler.calls == 1


async def test_Turn終端後の重複invokeも保存済みResultを返す(
    account: Account, ctx: ServiceContext
) -> None:
    executor, turn_id, handler = await _executor(account, ctx)
    call = ToolCall(name="sample_tool", stable_key="terminal-duplicate", arguments={"text": "x"})
    first = await executor.invoke(call)
    async with ctx.session_factory() as session, session.begin():
        await TurnRepository(session).finish_turn(
            turn_id, status=AgentTurnStatus.COMPLETED, now=ctx.clock.now()
        )

    second = await executor.invoke(call)

    assert second == first
    assert handler.calls == 1


async def test_未許可とauthorize拒否はFirewallとhandlerを呼ばず安全なEventを保存する(
    account: Account, ctx: ServiceContext
) -> None:
    executor, turn_id, handler = await _executor(account, ctx)
    result = await executor.invoke(ToolCall(name="unknown", stable_key="u-1", arguments={}))
    _, execution, events = await _rows(ctx, turn_id)

    assert result.error is not None and result.error.code == "TOOL_NOT_ALLOWED"
    assert handler.calls == 0
    assert execution.status == ToolExecutionStatus.BLOCKED
    assert events[0].event_type == SecurityEventType.UNAUTHORIZED_TOOL_CALL
    assert events[0].detector == SecurityDetector.APPLICATION
    assert events[0].event_metadata == {}
    assert "unknown" not in events[0].summary


async def test_authorize拒否ではFirewallとexecuteを呼ばない(
    account: Account, ctx: ServiceContext
) -> None:
    handler = RecordingHandler()
    handler.authorized = False
    executor, _, _ = await _executor(account, ctx, handler)
    firewall = ctx.agent_firewall

    result = await executor.invoke(
        ToolCall(name="sample_tool", stable_key="denied", arguments={"text": "secret"})
    )

    assert result.error is not None and result.error.code == "TOOL_AUTHORIZATION_DENIED"
    assert handler.calls == 0
    assert isinstance(firewall, FakeAgentFirewall)
    assert firewall.requests == []


async def test_schema不正はauthorize_Firewall_executeを呼ばずretryしない(
    account: Account, ctx: ServiceContext
) -> None:
    executor, _, handler = await _executor(account, ctx)
    result = await executor.invoke(
        ToolCall(name="sample_tool", stable_key="invalid", arguments={"text": 123})
    )
    assert result.error is not None and result.error.code == "TOOL_INPUT_INVALID"
    assert handler.authorize_calls == 0
    assert handler.calls == 0


async def test_Firewall_blockはraw値をEvent_Resultへ出さずexecuteしない(
    account: Account, ctx: ServiceContext
) -> None:
    executor, turn_id, handler = await _executor(account, ctx)
    firewall = ctx.agent_firewall
    assert isinstance(firewall, FakeAgentFirewall)
    firewall.decision = FirewallDecision.BLOCK
    raw = "user@example.com reason-from-provider"

    result = await executor.invoke(
        ToolCall(name="sample_tool", stable_key="blocked", arguments={"text": raw})
    )
    items, execution, events = await _rows(ctx, turn_id)
    combined = (
        repr(result.model_dump())
        + repr([item.content for item in items])
        + repr(events[0].event_metadata)
    )

    assert handler.calls == 0
    assert execution.status == ToolExecutionStatus.BLOCKED
    assert events[0].event_type == SecurityEventType.UNSAFE_EXTERNAL_ACTION
    assert raw not in combined
    assert "reason-from-provider" not in events[0].summary
    assert firewall.requests[0].masked_arguments["text"] == "[EMAIL] reason-from-provider"


async def test_Transientだけ再試行しattempt_countをphysical回数にする(
    account: Account, ctx: ServiceContext
) -> None:
    handler = RecordingHandler()
    handler.transient_failures = 2
    executor, turn_id, _ = await _executor(account, ctx, handler)
    result = await executor.invoke(
        ToolCall(name="sample_tool", stable_key="retry", arguments={"text": "x"})
    )
    _, execution, _ = await _rows(ctx, turn_id)
    assert result.success is True
    assert handler.calls == 3
    assert execution.attempt_count == 3


async def test_一般例外は1回で失敗する(account: Account, ctx: ServiceContext) -> None:
    handler = RecordingHandler()
    handler.error = RuntimeError("raw permanent detail")
    executor, turn_id, _ = await _executor(account, ctx, handler)
    result = await executor.invoke(
        ToolCall(name="sample_tool", stable_key="permanent", arguments={"text": "x"})
    )
    _, execution, _ = await _rows(ctx, turn_id)
    assert result.error is not None and result.error.code == "TOOL_EXECUTION_FAILED"
    assert handler.calls == 1
    assert execution.attempt_count == 1


async def test_Transientは上限で停止する(account: Account, ctx: ServiceContext) -> None:
    handler = RecordingHandler()
    handler.transient_failures = 10
    executor, turn_id, _ = await _executor(account, ctx, handler)
    result = await executor.invoke(
        ToolCall(name="sample_tool", stable_key="retry-limit", arguments={"text": "x"})
    )
    _, execution, _ = await _rows(ctx, turn_id)
    assert result.error is not None and result.error.code == "TOOL_RETRY_EXHAUSTED"
    assert handler.calls == ctx.settings.tool_max_attempts
    assert execution.attempt_count == ctx.settings.tool_max_attempts


async def test_output_schema不正は再試行せず宣言されたtrust分類で保存する(
    account: Account, ctx: ServiceContext
) -> None:
    handler = RecordingHandler()
    handler.output = {"value": 1}
    executor, turn_id, _ = await _executor(
        account,
        ctx,
        handler,
        source=AgentContentSource.WEB_CONTENT,
        context_class=AgentContextClass.UNTRUSTED_DATA,
    )
    result = await executor.invoke(
        ToolCall(name="sample_tool", stable_key="bad-output", arguments={"text": "x"})
    )
    items, execution, _ = await _rows(ctx, turn_id)
    assert result.error is not None and result.error.code == "TOOL_OUTPUT_INVALID"
    assert handler.calls == 1
    assert execution.attempt_count == 1
    assert items[-1].content_source == AgentContentSource.WEB_CONTENT
    assert items[-1].context_class == AgentContextClass.UNTRUSTED_DATA


async def test_Turn終端との遅延write競合ではResult_Event_Executionを更新しない(
    account: Account, ctx: ServiceContext
) -> None:
    handler = RecordingHandler()
    handler.gate = asyncio.Event()
    executor, turn_id, _ = await _executor(account, ctx, handler)
    task = asyncio.create_task(
        executor.invoke(ToolCall(name="sample_tool", stable_key="late", arguments={"text": "x"}))
    )
    await asyncio.wait_for(handler.started.wait(), 5)
    async with ctx.session_factory() as session, session.begin():
        await TurnRepository(session).finish_turn(
            turn_id, status=AgentTurnStatus.CANCELLED, now=ctx.clock.now()
        )
    handler.gate.set()
    result = await task
    items, execution, events = await _rows(ctx, turn_id)

    assert result.error is not None and result.error.code == "TOOL_TURN_ENDED"
    assert [item.item_type for item in items] == [AgentItemType.TOOL_CALL]
    assert execution.status == ToolExecutionStatus.CANCELLED
    assert execution.completed_at == ctx.clock.now()
    assert events == []


def _user_context(item_id: int, *, quarantined: bool = False) -> AgentContext:
    entry = AgentContextEntry(
        kind="item",
        role="user",
        content={"text": "remember"},
        turn_id=1,
        item_id=item_id,
        item_type=AgentItemType.USER_MESSAGE,
        context_class=AgentContextClass.CONVERSATION,
        content_source=AgentContentSource.USER_INPUT,
        context_status=(
            AgentItemContextStatus.QUARANTINED if quarantined else AgentItemContextStatus.ACTIVE
        ),
    )
    return AgentContext((entry,), 1)


@pytest.mark.parametrize("quarantined", [False, True])
async def test_provenanceはContext外と隔離済みUser入力を拒否する(
    account: Account, ctx: ServiceContext, *, quarantined: bool
) -> None:
    reference = (ToolProvenanceRef(source=ToolProvenance.USER_INPUT, item_id=123),)
    agent_context = _user_context(123, quarantined=True) if quarantined else None
    executor, _, handler = await _executor(account, ctx, agent_context=agent_context)
    result = await executor.invoke(
        ToolCall(
            name="sample_tool",
            stable_key="outside",
            arguments={"text": "x"},
            provenance=reference,
        )
    )
    assert result.error is not None and result.error.code == "TOOL_AUTHORIZATION_DENIED"
    assert handler.calls == 0


async def test_検証済みprovenanceを保存し同じstable_keyでの変更を競合にする(
    account: Account, ctx: ServiceContext
) -> None:
    executor, turn_id, handler = await _executor(account, ctx, agent_context=_user_context(42))
    first = await executor.invoke(
        ToolCall(
            name="sample_tool",
            stable_key="provenance-conflict",
            arguments={"text": "x"},
            provenance=(ToolProvenanceRef(source=ToolProvenance.USER_INPUT, item_id=42),),
        )
    )
    changed = await executor.invoke(
        ToolCall(
            name="sample_tool",
            stable_key="provenance-conflict",
            arguments={"text": "x"},
            provenance=(ToolProvenanceRef(source=ToolProvenance.SYSTEM),),
        )
    )
    items, _, _ = await _rows(ctx, turn_id)
    assert first.success is True
    assert changed.error is not None and changed.error.code == "TOOL_CALL_CONFLICT"
    assert items[0].content["provenance"] == [{"source": "user_input", "item_id": 42}]
    assert handler.calls == 1
