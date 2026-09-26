import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest

from agent_runtime.budget import TurnBudget
from agent_runtime.model import (
    GuardrailBlocked,
    ModelCallError,
    ModelMessage,
    ModelRequest,
    ModelResponseFormat,
    ModelTool,
    OrcaRouterModelClient,
)
from agent_runtime.runner import AgentRunError


def _response(*, content=None, calls=None, finish="stop", refusal=None, reasoning=None):
    message = SimpleNamespace(
        content=content,
        tool_calls=calls,
        refusal=refusal,
        reasoning=reasoning,
    )
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish)])


def _call(arguments: str = '{"query":"safe"}'):
    function = SimpleNamespace(name="web_search", arguments=arguments)
    return SimpleNamespace(id="provider-id", type="function", function=function)


def test_Model_parseはfinalとprivate_reasoningを分離する() -> None:
    decision = OrcaRouterModelClient._parse_response(
        _response(content=" answer ", reasoning="private chain of thought")
    )

    assert decision.final is not None
    assert decision.final.content == "answer"
    assert "reasoning" not in decision.model_dump_json()


def test_Model_parseは正確に1件のtool_callだけを許可する() -> None:
    decision = OrcaRouterModelClient._parse_response(
        _response(calls=[_call()], finish="tool_calls")
    )

    assert decision.tool_call is not None
    assert decision.tool_call.arguments == {"query": "safe"}


@pytest.mark.parametrize(
    "response",
    [
        _response(content="answer", calls=[_call()], finish="tool_calls"),
        _response(calls=[_call(), _call()], finish="tool_calls"),
        _response(calls=[_call("[]")], finish="tool_calls"),
        _response(content="", finish="stop"),
        _response(content="answer", refusal="blocked"),
    ],
)
def test_Model_parseは曖昧またはmalformedなdecisionを拒否する(response) -> None:
    with pytest.raises(ModelCallError, match="MODEL_MALFORMED_RESPONSE"):
        OrcaRouterModelClient._parse_response(response)


def test_Model_parseは出力上限をmalformedと分離する() -> None:
    with pytest.raises(ModelCallError, match="MODEL_OUTPUT_LIMIT_EXCEEDED"):
        OrcaRouterModelClient._parse_response(_response(content="answer", finish="length"))


class _Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value


def test_TurnBudgetは上限等値を許可しcost超過を拒否する() -> None:
    clock = _Clock()
    budget = TurnBudget(clock.now(), clock, 10, 2, Decimal("1.0"))
    budget.consume_step()
    budget.add_cost(Decimal("1.0"))

    with pytest.raises(AgentRunError, match="TURN_COST_LIMIT_EXCEEDED"):
        budget.consume_step()


def test_TurnBudgetはtimeをstepより先に検査する() -> None:
    clock = _Clock()
    budget = TurnBudget(clock.now(), clock, 10, 1, Decimal("1.0"), steps=1)
    clock.value += timedelta(seconds=10)

    with pytest.raises(AgentRunError, match="TURN_TIME_LIMIT_EXCEEDED"):
        budget.consume_step()


@pytest.mark.asyncio
async def test_OrcaRouter_Clientはheader_request_idとDecimal_costを返す(monkeypatch) -> None:
    captured = {}

    class _Create:
        async def create(self, **kwargs):
            captured.update(kwargs)
            response = _response(content="answer")
            response.usage = SimpleNamespace(prompt_tokens=12, completion_tokens=3)
            return SimpleNamespace(headers={"X-Orca-Request-Id": "req-1"}, parse=lambda: response)

    client = cast(Any, object.__new__(OrcaRouterModelClient))
    client._client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(with_raw_response=SimpleNamespace(create=_Create().create))
        )
    )
    client._model = "provider/model"
    client._timeout = 10

    async def confirmed_cost(request_id: str) -> Decimal:
        assert request_id == "req-1"
        return Decimal("0.01000001")

    monkeypatch.setattr(client, "_confirmed_cost", confirmed_cost)
    result = await client.complete(
        ModelRequest(
            messages=(ModelMessage(role="user", content="safe"),),
            tools=(
                ModelTool(
                    name="lookup",
                    description="Lookup",
                    parameters={
                        "type": "object",
                        "properties": {"id": {"type": "integer"}},
                        "required": ["id"],
                    },
                ),
            ),
            max_output_tokens=10,
            timeout_seconds=20,
            response_format=ModelResponseFormat(
                name="result",
                schema={
                    "type": "object",
                    "properties": {"answer": {"type": "string"}},
                    "required": ["answer"],
                },
            ),
            reasoning_effort="low",
        )
    )

    assert captured["extra_headers"] == {"X-OrcaRouter-Include-Cost": "true"}
    assert result.request_id == "req-1"
    assert result.cost_usd == Decimal("0.01000001")
    assert result.prompt_tokens == 12
    assert result.completion_tokens == 3
    assert captured["parallel_tool_calls"] is False
    assert captured["timeout"] == 20
    assert captured["tools"][0]["function"]["parameters"]["additionalProperties"] is False
    assert captured["reasoning_effort"] == "low"
    assert captured["response_format"]["type"] == "json_schema"
    assert captured["response_format"]["json_schema"]["strict"] is True
    assert captured["response_format"]["json_schema"]["schema"]["additionalProperties"] is False


@pytest.mark.asyncio
async def test_OrcaRouter_Clientはsecurity_error本文を公開しない() -> None:
    secret = "provider-secret-body"

    class _ProviderError(Exception):
        def __init__(self, message: str) -> None:
            super().__init__(message)
            self.status_code = 400
            self.body = {"code": "guardrail_blocked", "message": message}

    async def create(**kwargs):
        del kwargs
        raise _ProviderError(secret)

    client = cast(Any, object.__new__(OrcaRouterModelClient))
    client._client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(with_raw_response=SimpleNamespace(create=create))
        )
    )
    client._model = "provider/model"
    client._timeout = 10

    with pytest.raises(GuardrailBlocked) as info:
        await client.complete(
            ModelRequest(
                messages=(ModelMessage(role="user", content="safe"),), max_output_tokens=10
            )
        )
    assert secret not in str(info.value)
    assert secret not in vars(info.value)


@pytest.mark.asyncio
async def test_OrcaRouter_Clientはfirewall_errorをguardrailと分離しrequest_idを保持する() -> None:
    class _ProviderError(Exception):
        def __init__(self) -> None:
            super().__init__()
            self.status_code = 400
            self.body = {"code": "firewall_blocked"}
            self.response = SimpleNamespace(headers={"X-Orca-Request-Id": "blocked-request"})

    async def create(**kwargs):
        del kwargs
        raise _ProviderError

    client = cast(Any, object.__new__(OrcaRouterModelClient))
    client._client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(with_raw_response=SimpleNamespace(create=create))
        )
    )
    client._model = "provider/model"
    client._timeout = 10

    with pytest.raises(ModelCallError, match="MODEL_FIREWALL_BLOCKED") as info:
        await client.complete(
            ModelRequest(
                messages=(ModelMessage(role="user", content="safe"),), max_output_tokens=10
            )
        )
    assert info.value.request_id == "blocked-request"
    assert not isinstance(info.value, GuardrailBlocked)


@pytest.mark.asyncio
async def test_OrcaRouter_Clientは外側timeoutの変換を妨げない() -> None:
    async def create(**kwargs):
        del kwargs
        await asyncio.Event().wait()

    client = cast(Any, object.__new__(OrcaRouterModelClient))
    client._client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(with_raw_response=SimpleNamespace(create=create))
        )
    )
    client._model = "provider/model"
    client._timeout = 10

    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.01):
            await client.complete(
                ModelRequest(
                    messages=(ModelMessage(role="user", content="safe"),),
                    max_output_tokens=10,
                )
            )
