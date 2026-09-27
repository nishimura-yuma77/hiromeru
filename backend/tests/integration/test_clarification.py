import json
from decimal import Decimal
from typing import cast

from pydantic import JsonValue
from sqlalchemy import select

from agent_runtime.model import (
    FakeModelClient,
    FinalAnswer,
    ModelCallError,
    ModelDecision,
    ModelResult,
    ModelToolCall,
)
from agent_runtime.real_runner import RealAgentRunner
from api.sse import NullReporter
from domain.enums import AgentContentSource, AgentItemType, AgentType
from models import AgentItem
from repositories.agent import TurnRepository
from services.context import AuthContext, ServiceContext
from services.turn_service import TurnService
from tests.support.client import Account
from tests.support.fakes import FakeAgentRunner

QUESTIONS = ["募集したい職種は何ですか？", "採用で改善したいことは何ですか？"]


async def _ask(account: Account, ctx: ServiceContext, *, stream: bool = False) -> tuple[int, int]:
    session_id = await account.create_session()
    model = FakeModelClient(
        [
            ModelResult(
                decision=ModelDecision(
                    tool_call=ModelToolCall(
                        provider_id="ask-provider",
                        name="ask_user",
                        arguments=cast(dict[str, JsonValue], {"questions": QUESTIONS}),
                    )
                ),
                request_id=f"ask-{ctx.new_uuid().hex}",
                prompt_tokens=10,
                completion_tokens=4,
                cost_usd=Decimal("0.01"),
                latency_ms=20,
            )
        ]
    )
    object.__setattr__(ctx, "agent_runner", RealAgentRunner(ctx, model))
    response = await account.client.post(
        f"/api/v1/agent-sessions/{session_id}/turns",
        json={"message": "新しい採用施策を考える"},
        headers={"Accept": "text/event-stream"} if stream else {},
    )
    assert response.status_code == (200 if stream else 201), response.text
    if stream:
        events = [
            (block.splitlines()[0][7:], json.loads(block.splitlines()[1][6:]))
            for block in response.text.split("\n\n")
            if block.startswith("event: ")
        ]
        assert [name for name, _ in events] == [
            "turn_started",
            "activity_started",
            "activity_finished",
            "turn_finished",
        ]
        assert events[1][1]["name"] == "ask_user"
        turn = events[-1][1]
    else:
        turn = response.json()["data"]
    assert turn["status"] == "completed"
    assert [item["type"] for item in turn["items"]] == [
        "user_message",
        "clarification_request",
    ]
    assert turn["items"][1]["content"] == {"questions": QUESTIONS, "answered": False}
    return session_id, turn["agent_turn_id"]


def _reply(question_turn_id: int) -> dict:
    return {
        "clarification_response": {
            "question_turn_id": question_turn_id,
            "answers": [
                {"question_index": 0, "answer": "経験者エンジニア"},
                {"question_index": 1, "answer": "応募ページ流入を増やす"},
            ],
        }
    }


async def test_子Agentの情報不足から親が質問Toolを呼ぶ(
    account: Account, ctx: ServiceContext
) -> None:
    session_id = await account.create_session()

    async def body() -> bytes:
        return b'{"message":"new campaign"}'

    service = TurnService(ctx)
    prepared = await service.begin(
        AuthContext(account.marketer_id, account.company_id, account.marketer_id, account.email),
        session_id,
        body,
    )
    async with ctx.session_factory() as session:
        item = await session.scalar(
            select(AgentItem).where(
                AgentItem.agent_turn_id == prepared.turn_id,
                AgentItem.item_type == AgentItemType.USER_MESSAGE,
                AgentItem.content_source == AgentContentSource.USER_INPUT,
            )
        )
    assert item is not None

    def tool_result(name: str, arguments: dict[str, JsonValue]) -> ModelResult:
        return ModelResult(
            decision=ModelDecision(
                tool_call=ModelToolCall(
                    provider_id=f"provider-{name}", name=name, arguments=arguments
                )
            ),
            request_id=f"{name}-{ctx.new_uuid().hex}",
            prompt_tokens=10,
            completion_tokens=5,
            cost_usd=Decimal("0.01"),
            latency_ms=20,
        )

    child_output = '{"proposal":null,"missing_information":["募集したい職種は何ですか？"]}'
    model = FakeModelClient(
        [
            tool_result("run_campaign_planner", {"request_item_id": item.id}),
            ModelResult(
                decision=ModelDecision(final=FinalAnswer(content=child_output)),
                request_id=f"child-{ctx.new_uuid().hex}",
                prompt_tokens=10,
                completion_tokens=5,
                cost_usd=Decimal("0.01"),
                latency_ms=20,
            ),
            tool_result("ask_user", cast(dict[str, JsonValue], {"questions": [QUESTIONS[0]]})),
        ]
    )
    object.__setattr__(ctx, "agent_runner", RealAgentRunner(ctx, model))
    view = await service.execute(prepared, NullReporter())

    assert view.status == "completed"
    assert [item.type for item in view.items] == ["user_message", "clarification_request"]
    assert view.items[-1].content == {"questions": [QUESTIONS[0]], "answered": False}
    assert len(model.requests) == 3
    assert ctx.tool_registry.resolve(AgentType.CAMPAIGN_PLANNER, "ask_user") is None
    assert ctx.tool_registry.resolve(AgentType.CONTENT_CREATOR, "ask_user") is None


async def test_不正な質問Toolの結果は質問カードに表示しない(
    account: Account, ctx: ServiceContext
) -> None:
    session_id = await account.create_session()
    model = FakeModelClient(
        [
            ModelResult(
                decision=ModelDecision(
                    tool_call=ModelToolCall(
                        provider_id="invalid-ask",
                        name="ask_user",
                        arguments=cast(dict[str, JsonValue], {"questions": ["同じ？", "同じ？"]}),
                    )
                ),
                request_id=f"invalid-ask-{ctx.new_uuid().hex}",
                prompt_tokens=10,
                completion_tokens=4,
                cost_usd=Decimal("0.01"),
                latency_ms=20,
            ),
            ModelResult(
                decision=ModelDecision(final=FinalAnswer(content="確認方法を見直します。")),
                request_id=f"final-{ctx.new_uuid().hex}",
                prompt_tokens=10,
                completion_tokens=4,
                cost_usd=Decimal("0.01"),
                latency_ms=20,
            ),
        ]
    )
    object.__setattr__(ctx, "agent_runner", RealAgentRunner(ctx, model))
    response = await account.client.post(
        f"/api/v1/agent-sessions/{session_id}/turns", json={"message": "相談したい"}
    )

    assert response.status_code == 201
    turn = response.json()["data"]
    assert [item["type"] for item in turn["items"]] == ["user_message", "assistant_message"]
    async with ctx.session_factory() as session:
        tool_result = await session.scalar(
            select(AgentItem).where(
                AgentItem.agent_turn_id == turn["agent_turn_id"],
                AgentItem.item_type == AgentItemType.TOOL_RESULT,
            )
        )
    assert tool_result is not None
    assert tool_result.content["error"]["code"] == "INVALID_ARGUMENT"


async def _question(account: Account, session_id: int, question_turn_id: int) -> dict:
    response = await account.client.get(
        f"/api/v1/agent-sessions/{session_id}/turns/{question_turn_id}"
    )
    assert response.status_code == 200
    return response.json()["data"]["items"][1]["content"]


async def test_質問Toolは子Agentなしで終了し回答は元Turnに紐づく(
    account: Account, ctx: ServiceContext, agent: FakeAgentRunner
) -> None:
    session_id, question_turn_id = await _ask(account, ctx)
    object.__setattr__(ctx, "agent_runner", agent)

    unrelated = await account.client.post(
        f"/api/v1/agent-sessions/{session_id}/turns", json={"message": "別件を相談"}
    )
    assert unrelated.status_code == 201
    assert await _question(account, session_id, question_turn_id) == {
        "questions": QUESTIONS,
        "answered": False,
    }

    response = await account.client.post(
        f"/api/v1/agent-sessions/{session_id}/turns", json=_reply(question_turn_id)
    )
    assert response.status_code == 201, response.text
    content = response.json()["data"]["items"][0]["content"]
    assert content["clarification_response"] == _reply(question_turn_id)["clarification_response"]
    assert "質問1: 募集したい職種は何ですか？" in content["text"]
    assert "回答2: 応募ページ流入を増やす" in content["text"]
    assert (await _question(account, session_id, question_turn_id))["answered"] is True

    duplicate = await account.client.post(
        f"/api/v1/agent-sessions/{session_id}/turns", json=_reply(question_turn_id)
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "CLARIFICATION_ALREADY_ANSWERED"
    history = (await account.client.get(f"/api/v1/agent-sessions/{session_id}")).json()["data"]
    assert history["turns"][0]["items"][1]["content"]["answered"] is True


async def test_質問はSSEの終端とTurn取得で同じ内容になる(
    account: Account, ctx: ServiceContext
) -> None:
    session_id, question_turn_id = await _ask(account, ctx, stream=True)
    assert await _question(account, session_id, question_turn_id) == {
        "questions": QUESTIONS,
        "answered": False,
    }


async def test_回答は所属と質問番号を検証し不正時にはTurnを作らない(
    account: Account, new_account, ctx: ServiceContext
) -> None:
    session_id, question_turn_id = await _ask(account, ctx)
    stranger = await new_account()
    path = f"/api/v1/agent-sessions/{session_id}/turns"
    unauthorized = await stranger.client.post(
        f"/api/v1/agent-sessions/{await stranger.create_session()}/turns",
        json=_reply(question_turn_id),
    )
    assert unauthorized.status_code == 404
    assert unauthorized.json()["error"]["code"] == "CLARIFICATION_REQUEST_NOT_FOUND"

    invalid = [
        {"message": "text", **_reply(question_turn_id)},
        {"clarification_response": {"question_turn_id": question_turn_id, "answers": []}},
        {
            "clarification_response": {
                "question_turn_id": question_turn_id,
                "answers": [
                    {"question_index": 1, "answer": "逆順"},
                    {"question_index": 0, "answer": "逆順"},
                ],
            }
        },
        {
            "clarification_response": {
                "question_turn_id": question_turn_id,
                "answers": [
                    {"question_index": 0, "answer": "x" * 1001},
                    {"question_index": 1, "answer": "ok"},
                ],
            }
        },
    ]
    for body in invalid:
        response = await account.client.post(path, json=body)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_ARGUMENT"
    history = (await account.client.get(f"/api/v1/agent-sessions/{session_id}")).json()["data"]
    assert len(history["turns"]) == 1


async def test_失敗または隔離された回答は再回答できる(
    account: Account, ctx: ServiceContext, agent: FakeAgentRunner
) -> None:
    session_id, question_turn_id = await _ask(account, ctx)
    object.__setattr__(ctx, "agent_runner", agent)
    path = f"/api/v1/agent-sessions/{session_id}/turns"
    agent.error = ModelCallError("MODEL_PROVIDER_ERROR")
    failed = await account.client.post(path, json=_reply(question_turn_id))
    assert failed.status_code == 500
    assert (await _question(account, session_id, question_turn_id))["answered"] is False

    agent.error = None
    succeeded = await account.client.post(path, json=_reply(question_turn_id))
    assert succeeded.status_code == 201
    answer_turn_id = succeeded.json()["data"]["agent_turn_id"]
    assert (await _question(account, session_id, question_turn_id))["answered"] is True

    async with ctx.session_factory() as session, session.begin():
        item = await session.scalar(
            select(AgentItem).where(
                AgentItem.agent_turn_id == answer_turn_id,
                AgentItem.item_type == AgentItemType.USER_MESSAGE,
            )
        )
        assert item is not None
        assert await TurnRepository(session).quarantine_item(
            item.id,
            reason="prompt_injection",
            context_override={"security_notice": "Untrusted content was quarantined."},
            now=ctx.clock.now(),
        )
    assert (await _question(account, session_id, question_turn_id))["answered"] is False
    retry = await account.client.post(path, json=_reply(question_turn_id))
    assert retry.status_code == 201
    assert (await _question(account, session_id, question_turn_id))["answered"] is True
