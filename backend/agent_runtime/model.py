"""Provider非依存Model境界とOrcaRouter Chat Completions adapter。"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from decimal import Decimal, InvalidOperation
from time import monotonic
from typing import Any, Literal, Protocol, cast

import httpx
from agents import set_default_openai_api, set_default_openai_client, set_tracing_disabled
from agents.strict_schema import ensure_strict_json_schema
from openai import APITimeoutError, AsyncOpenAI
from pydantic import Field, JsonValue, ValidationError, model_validator

from agent_runtime.tools import StrictToolModel


class ModelMessageToolCall(StrictToolModel):
    """Chat履歴中のfunction call。"""

    id: str
    name: str
    arguments: dict[str, JsonValue]


class ModelMessage(StrictToolModel):
    """モデルへ渡せる公開Chat message。"""

    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_call_id: str | None = None
    tool_calls: tuple[ModelMessageToolCall, ...] = ()

    @model_validator(mode="after")
    def _role_shape(self) -> "ModelMessage":
        if self.role == "assistant" and len(self.tool_calls) == 1 and self.content is None:
            return self
        if self.role == "tool" and self.tool_call_id and self.content is not None:
            return self
        if (
            self.role in {"system", "user", "assistant"}
            and self.content is not None
            and not self.tool_calls
            and self.tool_call_id is None
        ):
            return self
        raise ValueError("invalid message shape")


class ModelTool(StrictToolModel):
    """strict function tool定義。"""

    name: str
    description: str
    parameters: dict[str, JsonValue]


class ModelRequest(StrictToolModel):
    """Provider非依存のnon-streaming request。"""

    messages: tuple[ModelMessage, ...] = Field(min_length=1)
    tools: tuple[ModelTool, ...] = ()
    max_output_tokens: int = Field(gt=0)


class FinalAnswer(StrictToolModel):
    """非空の最終回答。"""

    content: str = Field(min_length=1)


class ModelToolCall(StrictToolModel):
    """正確に1件のfunction call。Provider IDは永続keyに使わない。"""

    provider_id: str
    name: str
    arguments: dict[str, JsonValue]


class ModelDecision(StrictToolModel):
    """最終回答または1 tool callの排他的decision。"""

    final: FinalAnswer | None = None
    tool_call: ModelToolCall | None = None

    @model_validator(mode="after")
    def _xor(self) -> "ModelDecision":
        if (self.final is None) == (self.tool_call is None):
            raise ValueError("exactly one decision is required")
        return self


class ModelResult(StrictToolModel):
    """保存可能な最小telemetryを伴うモデル結果。"""

    decision: ModelDecision
    request_id: str
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    cost_usd: Decimal = Field(ge=0)
    latency_ms: int = Field(ge=0)


class ModelCallError(Exception):
    """Provider本文を保持しない固定分類のcall失敗。"""

    def __init__(
        self,
        code: str,
        *,
        request_id: str | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        cost_usd: Decimal | None = None,
        latency_ms: int | None = None,
    ) -> None:
        """固定codeと安全なtelemetryだけを保持する。"""
        super().__init__(code)
        self.code = code
        self.request_id = request_id
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.cost_usd = cost_usd
        self.latency_ms = latency_ms


class GuardrailBlocked(ModelCallError):  # noqa: N818 - 公開契約名
    """OrcaRouter input guardrail block。理由やraw contentは保持しない。"""

    def __init__(
        self,
        *,
        target_item_ids: tuple[int, ...] = (),
        request_id: str | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        cost_usd: Decimal | None = None,
        latency_ms: int | None = None,
    ) -> None:
        """Safe target IDとtelemetryだけを保持する。"""
        super().__init__(
            "MODEL_GUARDRAIL_BLOCKED",
            request_id=request_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
        )
        self.target_item_ids = target_item_ids


class ModelClient(Protocol):
    """モデル呼び出しのtyped境界。"""

    async def complete(self, request: ModelRequest) -> ModelResult:
        """1件の厳格なdecisionを返す。"""
        ...


class FakeModelClient:
    """decisionまたは例外を順番に返すscript client。"""

    def __init__(self, script: list[ModelResult | Exception]) -> None:
        """返却scriptを設定する。"""
        self.script = script
        self.requests: list[ModelRequest] = []

    async def complete(self, request: ModelRequest) -> ModelResult:
        """次のscript要素を返す。"""
        self.requests.append(request)
        if not self.script:
            raise ModelCallError("MODEL_PROVIDER_ERROR")
        result = self.script.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class OrcaRouterModelClient:
    """OpenAI SDK raw response APIを使うOrcaRouter adapter。"""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float,
        generation_lookup_attempts: int,
        generation_lookup_backoff_seconds: float,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """SDK clientをtrace無効で初期化する。"""
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key, max_retries=0)
        set_default_openai_client(self._client, use_for_tracing=False)
        set_default_openai_api("chat_completions")
        set_tracing_disabled(True)
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_seconds
        self._attempts = generation_lookup_attempts
        self._backoff = generation_lookup_backoff_seconds
        self._sleep = sleep

    async def complete(self, request: ModelRequest) -> ModelResult:  # noqa: PLR0915
        """Chatを1回実行し、確定cost取得後に結果を返す。"""
        started = monotonic()
        request_id: str | None = None
        prompt_tokens: int | None = None
        completion_tokens: int | None = None
        cost_usd: Decimal | None = None
        try:
            kwargs: dict[str, Any] = {
                "model": self._model,
                "messages": [self._message_payload(message) for message in request.messages],
                "max_completion_tokens": request.max_output_tokens,
                "stream": False,
                "extra_headers": {"X-OrcaRouter-Include-Cost": "true"},
                "timeout": self._timeout,
            }
            if request.tools:
                kwargs["tools"] = [self._tool_payload(tool) for tool in request.tools]
                kwargs["parallel_tool_calls"] = False
            raw = await self._client.chat.completions.with_raw_response.create(**cast(Any, kwargs))
            request_id = raw.headers.get("X-Orca-Request-Id")
            response = raw.parse()
            usage = response.usage
            if usage is None:
                raise ModelCallError("MODEL_USAGE_MISSING")
            prompt_tokens = int(usage.prompt_tokens)
            completion_tokens = int(usage.completion_tokens)
            cost_usd = self._usage_cost(usage)
            if prompt_tokens < 0 or completion_tokens < 0:
                raise ModelCallError("MODEL_USAGE_INVALID")
            decision = self._parse_response(response)
            if not request_id:
                raise ModelCallError("MODEL_REQUEST_ID_MISSING")
            cost = await self._confirmed_cost(request_id)
            return ModelResult(
                decision=decision,
                request_id=request_id,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=cost,
                latency_ms=int((monotonic() - started) * 1000),
            )
        except asyncio.CancelledError as error:
            # asyncio.timeout()がTimeoutErrorへ変換できるよう元の例外を再送出する。
            telemetry = cast(Any, error)
            telemetry.request_id = request_id
            telemetry.prompt_tokens = prompt_tokens
            telemetry.completion_tokens = completion_tokens
            telemetry.cost_usd = cost_usd
            telemetry.latency_ms = int((monotonic() - started) * 1000)
            raise
        except GuardrailBlocked as error:
            error.cost_usd = error.cost_usd or cost_usd
            raise
        except ModelCallError as error:
            error.request_id = error.request_id or request_id
            error.prompt_tokens = (
                error.prompt_tokens if error.prompt_tokens is not None else prompt_tokens
            )
            error.completion_tokens = (
                error.completion_tokens
                if error.completion_tokens is not None
                else completion_tokens
            )
            error.cost_usd = error.cost_usd or cost_usd
            error.latency_ms = error.latency_ms or int((monotonic() - started) * 1000)
            raise
        except Exception as error:  # noqa: BLE001 - SDK例外を固定分類へ変換する境界
            status = getattr(error, "status_code", None)
            body = getattr(error, "body", None)
            code = None
            if isinstance(body, dict):
                nested = body.get("error")
                code = nested.get("code") if isinstance(nested, dict) else body.get("code")
            latency = int((monotonic() - started) * 1000)
            response = getattr(error, "response", None)
            headers = getattr(response, "headers", {})
            request_id = (
                request_id
                or getattr(error, "request_id", None)
                or headers.get("X-Orca-Request-Id")
                or headers.get("x-request-id")
            )
            if status == 400 and code == "guardrail_blocked":
                raise GuardrailBlocked(request_id=request_id, latency_ms=latency) from None
            if status == 400 and code in {"firewall_blocked", "firewall_approval_pending"}:
                raise ModelCallError(
                    "MODEL_FIREWALL_BLOCKED", request_id=request_id, latency_ms=latency
                ) from None
            if isinstance(error, TimeoutError | httpx.TimeoutException | APITimeoutError):
                raise ModelCallError(
                    "MODEL_TIMEOUT", request_id=request_id, latency_ms=latency
                ) from None
            raise ModelCallError(
                "MODEL_PROVIDER_ERROR", request_id=request_id, latency_ms=latency
            ) from None

    @staticmethod
    def _tool_payload(tool: ModelTool) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": ensure_strict_json_schema(tool.parameters),
                "strict": True,
            },
        }

    @staticmethod
    def _message_payload(message: ModelMessage) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": message.role, "content": message.content}
        if message.tool_call_id is not None:
            payload["tool_call_id"] = message.tool_call_id
        if message.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(
                            call.arguments,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    },
                }
                for call in message.tool_calls
            ]
        return payload

    @staticmethod
    def _usage_cost(usage: Any) -> Decimal | None:  # noqa: ANN401 - SDK型の拡張field
        """確定Cost取得失敗時の上限管理に使う暫定Costを安全に読む。"""
        raw = getattr(usage, "cost_usd", None)
        if raw is None and isinstance(getattr(usage, "model_extra", None), dict):
            raw = usage.model_extra.get("cost_usd")
        if raw is None:
            return None
        try:
            cost = Decimal(str(raw))
        except InvalidOperation:
            return None
        return cost if cost.is_finite() and cost >= 0 else None

    @staticmethod
    def _parse_response(response: Any) -> ModelDecision:  # noqa: ANN401
        try:
            if len(response.choices) != 1:
                raise ValueError
            choice = response.choices[0]
            message = choice.message
            calls = message.tool_calls or []
            content = message.content
            refusal = getattr(message, "refusal", None)
            if refusal:
                raise ValueError
            if choice.finish_reason == "stop" and not calls and isinstance(content, str):
                stripped = content.strip()
                if not stripped:
                    raise ValueError
                return ModelDecision(final=FinalAnswer(content=stripped))
            if choice.finish_reason != "tool_calls" or len(calls) != 1 or content:
                raise ValueError
            call = calls[0]
            if getattr(call, "type", None) != "function":
                raise ValueError
            arguments = json.loads(call.function.arguments)
            if not isinstance(arguments, dict):
                raise ValueError
            return ModelDecision(
                tool_call=ModelToolCall(
                    provider_id=call.id,
                    name=call.function.name,
                    arguments=arguments,
                )
            )
        except (AttributeError, TypeError, ValueError, json.JSONDecodeError, ValidationError):
            raise ModelCallError("MODEL_MALFORMED_RESPONSE") from None

    async def _confirmed_cost(self, request_id: str) -> Decimal:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        async with httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client:
            for attempt in range(self._attempts):
                try:
                    response = await client.get(
                        f"{self._base_url}/generation", params={"id": request_id}, headers=headers
                    )
                except httpx.HTTPError:
                    raise ModelCallError("MODEL_COST_LOOKUP_FAILED") from None
                if response.status_code == 404 and attempt + 1 < self._attempts:
                    await self._sleep(self._backoff * (attempt + 1))
                    continue
                if response.status_code != 200:
                    raise ModelCallError("MODEL_COST_LOOKUP_FAILED")
                try:
                    data = response.json()["data"]
                    if data["cost_currency"] != "USD":
                        raise ValueError
                    cost = Decimal(str(data["total_cost"]))
                    if not cost.is_finite() or cost < 0:
                        raise ValueError
                    return cost
                except (KeyError, TypeError, ValueError, InvalidOperation):
                    raise ModelCallError("MODEL_COST_LOOKUP_FAILED") from None
        raise ModelCallError("MODEL_COST_LOOKUP_FAILED")
