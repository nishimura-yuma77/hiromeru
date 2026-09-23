import asyncio
from decimal import Decimal

from sqlalchemy import select

from agent_runtime.model import (
    FakeModelClient,
    FinalAnswer,
    GuardrailBlocked,
    ModelCallError,
    ModelDecision,
    ModelResult,
    ModelToolCall,
)
from agent_runtime.real_runner import RealAgentRunner
from domain.enums import (
    AgentContentSource,
    AgentContextClass,
    AgentItemContextStatus,
    AgentItemType,
    AgentTurnStatus,
)
from models import AgentItem, LlmCall, SecurityEvent
from repositories.agent import SessionRepository, TurnRepository
from services.context import ServiceContext
from tests.support.client import Account


def _final(request_id: str, content: str = "最終回答です", cost: str = "0.01") -> ModelResult:
    return ModelResult(
        decision=ModelDecision(final=FinalAnswer(content=content)),
        request_id=request_id,
        prompt_tokens=10,
        completion_tokens=3,
        cost_usd=Decimal(cost),
        latency_ms=20,
    )


def _tool(request_id: str, name: str, arguments: dict) -> ModelResult:
    return ModelResult(
        decision=ModelDecision(
            tool_call=ModelToolCall(
                provider_id=f"provider-{request_id}", name=name, arguments=arguments
            )
        ),
        request_id=request_id,
        prompt_tokens=8,
        completion_tokens=4,
        cost_usd=Decimal("0.01"),
        latency_ms=15,
    )


def _use_real_runner(ctx: ServiceContext, script: list[ModelResult | Exception]) -> FakeModelClient:
    model = FakeModelClient(script)
    object.__setattr__(ctx, "agent_runner", RealAgentRunner(ctx, model))
    return model


def _rid(ctx: ServiceContext, label: str) -> str:
    return f"{label}-{ctx.new_uuid().hex}"


async def test_実Runnerはmulti_step_loopを実行しLLM生成元を関連付ける(
    account: Account, ctx: ServiceContext
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    tool_request_id = _rid(ctx, "runner-loop-tool")
    final_request_id = _rid(ctx, "runner-loop-final")
    model = _use_real_runner(
        ctx,
        [
            _tool(tool_request_id, "get_campaign", {"campaign_id": campaign_id}),
            _final(final_request_id),
        ],
    )

    response = await account.client.post(
        f"/api/v1/agent-sessions/{session_id}/turns", json={"message": "施策を確認して"}
    )

    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["status"] == "completed"
    assert [item["type"] for item in data["items"]] == [
        "user_message",
        "assistant_message",
    ]
    assert data["items"][-1]["content"] == {"text": "最終回答です"}
    assert len(model.requests) == 2
    assert model.requests[0].tools
    async with ctx.session_factory() as session:
        calls = list(
            (
                await session.execute(
                    select(LlmCall)
                    .where(LlmCall.agent_turn_id == data["agent_turn_id"])
                    .order_by(LlmCall.id)
                )
            ).scalars()
        )
        items = list(
            (
                await session.execute(
                    select(AgentItem)
                    .where(AgentItem.agent_turn_id == data["agent_turn_id"])
                    .order_by(AgentItem.item_number)
                )
            ).scalars()
        )
    assert [call.orcarouter_request_id for call in calls] == [
        tool_request_id,
        final_request_id,
    ]
    assert all(call.succeeded for call in calls)
    user_item = next(item for item in items if item.item_type == AgentItemType.USER_MESSAGE)
    tool_call = next(item for item in items if item.item_type == AgentItemType.TOOL_CALL)
    assistant = next(item for item in items if item.item_type == AgentItemType.ASSISTANT_MESSAGE)
    assert {"source": "user_input", "item_id": user_item.id} in tool_call.content["provenance"]
    assert tool_call.llm_call_id == calls[0].id
    assert assistant.llm_call_id == calls[1].id


async def test_実Runnerはmodel失敗を本文なしで保存する(
    account: Account, ctx: ServiceContext
) -> None:
    session_id = await account.create_session()
    request_id = _rid(ctx, "runner-malformed")
    _use_real_runner(
        ctx,
        [
            ModelCallError(
                "MODEL_MALFORMED_RESPONSE",
                request_id=request_id,
                prompt_tokens=7,
                completion_tokens=2,
                cost_usd=Decimal("0.02"),
                latency_ms=12,
            )
        ],
    )

    response = await account.client.post(
        f"/api/v1/agent-sessions/{session_id}/turns", json={"message": "確認して"}
    )

    assert response.status_code == 500
    turn_id = response.json()["error"]["agent_turn_id"]
    async with ctx.session_factory() as session:
        call = await session.scalar(select(LlmCall).where(LlmCall.agent_turn_id == turn_id))
    assert call is not None
    assert call.succeeded is False
    assert call.error_code == "MODEL_MALFORMED_RESPONSE"
    assert call.error_message == "The model request failed."
    assert call.cost_usd == Decimal("0.02000000")


async def test_実Runnerは過去Turnのuntrusted_itemを隔離して再実行する(
    account: Account, ctx: ServiceContext
) -> None:
    session_id = await account.create_session()
    async with ctx.session_factory() as session, session.begin():
        assert await SessionRepository(session).get_parent(
            account.marketer_id, session_id, lock=True
        )
        previous = await TurnRepository(session).create_turn(session_id, ctx.clock.now())
        await TurnRepository(session).append_item(
            previous.id,
            key="prior-user",
            item_type=AgentItemType.USER_MESSAGE,
            source=AgentContentSource.USER_INPUT,
            content={"text": "前の依頼"},
            now=ctx.clock.now(),
        )
        unsafe = await TurnRepository(session).append_item(
            previous.id,
            key="unsafe-history",
            item_type=AgentItemType.ASSISTANT_MESSAGE,
            source=AgentContentSource.WEB_CONTENT,
            context_class=AgentContextClass.UNTRUSTED_DATA,
            content={"text": "unsafe external content"},
            now=ctx.clock.now(),
        )
        await TurnRepository(session).finish_turn(
            previous.id, status=AgentTurnStatus.COMPLETED, now=ctx.clock.now()
        )
    _use_real_runner(
        ctx,
        [
            GuardrailBlocked(
                target_item_ids=(unsafe.id,), request_id=_rid(ctx, "runner-guardrail")
            ),
            _final(_rid(ctx, "runner-recovered")),
        ],
    )

    response = await account.client.post(
        f"/api/v1/agent-sessions/{session_id}/turns", json={"message": "安全に続けて"}
    )

    assert response.status_code == 201, response.text
    turn_id = response.json()["data"]["agent_turn_id"]
    async with ctx.session_factory() as session:
        quarantined = await session.get(AgentItem, unsafe.id)
        event = await session.scalar(
            select(SecurityEvent).where(SecurityEvent.agent_turn_id == turn_id)
        )
    assert quarantined is not None
    assert quarantined.context_status == AgentItemContextStatus.QUARANTINED
    assert event is not None
    assert event.agent_item_id is None
    assert event.event_metadata == {"source_item_id": unsafe.id}


async def test_実Runnerは対象不明のguardrail_blockをfail_closedにする(
    account: Account, ctx: ServiceContext
) -> None:
    session_id = await account.create_session()
    _use_real_runner(ctx, [GuardrailBlocked(request_id=_rid(ctx, "runner-blocked"))])

    response = await account.client.post(
        f"/api/v1/agent-sessions/{session_id}/turns", json={"message": "確認して"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "TURN_BLOCKED"
    turn_id = response.json()["error"]["agent_turn_id"]
    async with ctx.session_factory() as session:
        event = await session.scalar(
            select(SecurityEvent).where(SecurityEvent.agent_turn_id == turn_id)
        )
    assert event is not None and event.agent_item_id is None


async def test_実Runnerはcost超過したLLM出力を採用しない(
    account: Account, ctx: ServiceContext
) -> None:
    session_id = await account.create_session()
    _use_real_runner(ctx, [_final(_rid(ctx, "runner-over-cost"), cost="1.01")])

    response = await account.client.post(
        f"/api/v1/agent-sessions/{session_id}/turns", json={"message": "確認して"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "TURN_COST_LIMIT_EXCEEDED"
    turn_id = response.json()["error"]["agent_turn_id"]
    async with ctx.session_factory() as session:
        call = await session.scalar(select(LlmCall).where(LlmCall.agent_turn_id == turn_id))
        assistant = await session.scalar(
            select(AgentItem).where(
                AgentItem.agent_turn_id == turn_id,
                AgentItem.item_type == AgentItemType.ASSISTANT_MESSAGE,
            )
        )
    assert call is not None and call.cost_usd == Decimal("1.01000000")
    assert assistant is None


async def test_実Runnerはstep上限到達後にtoolを実行しない(
    account: Account, ctx: ServiceContext
) -> None:
    session_id = await account.create_session()
    object.__setattr__(ctx.settings, "agent_max_steps", 1)
    _use_real_runner(
        ctx, [_tool(_rid(ctx, "runner-step-limit"), "get_campaign", {"campaign_id": 1})]
    )

    response = await account.client.post(
        f"/api/v1/agent-sessions/{session_id}/turns", json={"message": "確認して"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "TURN_STEP_LIMIT_EXCEEDED"
    turn_id = response.json()["error"]["agent_turn_id"]
    async with ctx.session_factory() as session:
        items = list(
            (
                await session.execute(select(AgentItem).where(AgentItem.agent_turn_id == turn_id))
            ).scalars()
        )
    assert [item.item_type for item in items] == [AgentItemType.USER_MESSAGE]


async def test_実Runnerはtime上限でcancelled_LLM_callを保存する(
    account: Account, ctx: ServiceContext
) -> None:
    class _HangingModelClient:
        async def complete(self, request) -> ModelResult:
            del request
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    session_id = await account.create_session()
    object.__setattr__(ctx.settings, "turn_time_limit_seconds", 0.2)
    object.__setattr__(ctx, "agent_runner", RealAgentRunner(ctx, _HangingModelClient()))

    response = await account.client.post(
        f"/api/v1/agent-sessions/{session_id}/turns", json={"message": "確認して"}
    )

    assert response.status_code == 504
    assert response.json()["error"]["code"] == "TURN_TIME_LIMIT_EXCEEDED"
    turn_id = response.json()["error"]["agent_turn_id"]
    async with ctx.session_factory() as session:
        call = await session.scalar(select(LlmCall).where(LlmCall.agent_turn_id == turn_id))
    assert call is not None
    assert call.succeeded is False
    assert call.error_code == "MODEL_CANCELLED"
