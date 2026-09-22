"""Tool Callの永続化、認可、Firewall、実行、retryを統括する。"""

import asyncio
from contextlib import suppress
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ValidationError

from agent_runtime.firewall import FirewallDecision, FirewallRequest
from agent_runtime.runner import ActivityStatus, AgentContext, AgentContextEntry, ProgressReporter
from agent_runtime.tools import (
    ToolCall,
    ToolDefinition,
    ToolDomainError,
    ToolError,
    ToolProvenance,
    ToolProvenanceRef,
    ToolResult,
    TransientToolError,
    TrustedToolContext,
)
from core.masking import mask_json, mask_text
from domain.enums import (
    AgentContentSource,
    AgentContextClass,
    AgentItemContextStatus,
    AgentItemType,
    AgentTurnStatus,
    SecurityDetector,
    SecurityEventType,
    ToolExecutionStatus,
)
from repositories.agent import (
    PreparedToolExecution,
    ToolCallConflictError,
    ToolExecutionRepository,
)
from services.context import ServiceContext

_ERROR_MESSAGES = {
    "TOOL_NOT_ALLOWED": "This tool is not available for the current agent.",
    "TOOL_INPUT_INVALID": "The tool input is invalid.",
    "TOOL_AUTHORIZATION_DENIED": "The tool call was not authorized.",
    "TOOL_FIREWALL_BLOCKED": "The tool call was blocked by a security control.",
    "TOOL_EXECUTION_FAILED": "The tool could not be completed.",
    "TOOL_OUTPUT_INVALID": "The tool returned an invalid result.",
    "TOOL_RETRY_EXHAUSTED": "The tool could not be completed after retrying.",
    "TOOL_TURN_ENDED": "The tool call was cancelled because the turn ended.",
    "TOOL_EXECUTION_IN_PROGRESS": "The same tool call is already running.",
    "TOOL_CALL_CONFLICT": "The tool call key was reused with different input.",
}


def _failure(code: str, *, retryable: bool = False, message: str | None = None) -> ToolResult:
    return ToolResult(
        success=False,
        data=None,
        error=ToolError(code=code, message=message or _ERROR_MESSAGES[code], retryable=retryable),
    )


class ToolExecutor:
    """1つのTurnだけに束縛されたTool Runtime。"""

    def __init__(
        self,
        ctx: ServiceContext,
        *,
        marketer_id: int,
        company_id: int,
        session_id: int,
        turn_id: int,
        reporter: ProgressReporter,
        agent_context: AgentContext | None = None,
    ) -> None:
        """認証済みTenantと現在TurnへExecutorを束縛する。"""
        self._ctx = ctx
        self._marketer_id = marketer_id
        self._company_id = company_id
        self._session_id = session_id
        self._turn_id = turn_id
        self._reporter = reporter
        self._agent_context = agent_context or AgentContext((), 0)

    async def invoke(  # noqa: PLR0912, PLR0915 - 永続化から終端保存までの単一境界
        self, call: ToolCall, parent_activity_id: str | None = None
    ) -> ToolResult:
        """論理Callを一度だけ実行する。"""
        context = await self._trusted_context()
        if context is None:
            return _failure("TOOL_TURN_ENDED")
        definition = self._ctx.tool_registry.resolve(context.agent_type, call.name)
        provenance_valid = self._validate_provenance(call.provenance)
        context = context.model_copy(
            update={"provenance": call.provenance if provenance_valid else ()}
        )
        validated_input = None
        input_error = False
        if definition is not None:
            try:
                validated_input = definition.input_model.model_validate(call.arguments)
            except ValidationError:
                input_error = True
        persisted_arguments = (
            mask_json(validated_input.model_dump(mode="json"))
            if validated_input is not None
            else mask_json(call.arguments)
        )
        persisted_provenance = (
            [reference.model_dump(mode="json") for reference in call.provenance]
            if provenance_valid
            else []
        )
        if context.turn_status != AgentTurnStatus.RUNNING:
            try:
                terminal = await self._terminal_by_key(
                    call, persisted_arguments, persisted_provenance
                )
            except ToolCallConflictError:
                return _failure("TOOL_CALL_CONFLICT")
            return terminal or _failure("TOOL_TURN_ENDED")

        try:
            prepared = await self._prepare(call, persisted_arguments, persisted_provenance)
        except ToolCallConflictError:
            return _failure("TOOL_CALL_CONFLICT")
        if prepared is None:
            return _failure("TOOL_TURN_ENDED")
        if prepared.terminal_result is not None:
            return ToolResult.model_validate(prepared.terminal_result.content)
        if not await self._claim(prepared):
            terminal = await self._terminal(prepared)
            return terminal or _failure("TOOL_EXECUTION_IN_PROGRESS")

        activity_id = self._activity_started(mask_text(call.name), parent_activity_id)
        result: ToolResult
        status: ToolExecutionStatus
        event_type: SecurityEventType | None = None
        detector: SecurityDetector | None = None
        result_source = AgentContentSource.SYSTEM
        result_class = AgentContextClass.CONVERSATION
        if not provenance_valid:
            result = _failure("TOOL_AUTHORIZATION_DENIED")
            status = ToolExecutionStatus.BLOCKED
            event_type = SecurityEventType.UNAUTHORIZED_TOOL_CALL
            detector = SecurityDetector.APPLICATION
        elif definition is None:
            result = _failure("TOOL_NOT_ALLOWED")
            status = ToolExecutionStatus.BLOCKED
            event_type = SecurityEventType.UNAUTHORIZED_TOOL_CALL
            detector = SecurityDetector.APPLICATION
        elif input_error or validated_input is None:
            invalid = definition.errors.get("INVALID_ARGUMENT")
            result = (
                _failure(
                    "INVALID_ARGUMENT",
                    retryable=invalid.retryable,
                    message=invalid.message,
                )
                if invalid is not None
                else _failure("TOOL_INPUT_INVALID")
            )
            status = ToolExecutionStatus.FAILED
        else:
            result_source = definition.result_source
            result_class = definition.result_context_class
            result, status, event_type, detector = await self._run_allowed(
                context, call, definition, validated_input, prepared
            )
        saved = await self._finish(
            prepared,
            result,
            status,
            result_source,
            result_class,
            event_type,
            detector,
        )
        final_status = (
            "blocked"
            if status == ToolExecutionStatus.BLOCKED
            else ("succeeded" if status == ToolExecutionStatus.COMPLETED else "failed")
        )
        self._activity_finished(activity_id, final_status)
        return result if saved else _failure("TOOL_TURN_ENDED")

    async def _run_allowed(
        self,
        context: TrustedToolContext,
        call: ToolCall,
        definition: ToolDefinition,
        validated_input: BaseModel,
        prepared: PreparedToolExecution,
    ) -> tuple[
        ToolResult,
        ToolExecutionStatus,
        SecurityEventType | None,
        SecurityDetector | None,
    ]:
        try:
            authorized = await definition.handler.authorize(context, validated_input)
        except ToolDomainError as error:
            return self._domain_failure(definition, error)
        except Exception:  # noqa: BLE001 - 詳細を外へ出さないpermanent failure
            return _failure("TOOL_EXECUTION_FAILED"), ToolExecutionStatus.FAILED, None, None
        if not authorized:
            return (
                _failure("TOOL_AUTHORIZATION_DENIED"),
                ToolExecutionStatus.BLOCKED,
                SecurityEventType.UNAUTHORIZED_TOOL_CALL,
                SecurityDetector.APPLICATION,
            )
        request = FirewallRequest(
            tool_name=call.name,
            masked_arguments=mask_json(validated_input.model_dump(mode="json")),
            agent_type=context.agent_type,
            provenance=call.provenance,
            stable_key=call.stable_key,
        )
        try:
            decision = await self._ctx.agent_firewall.inspect(request)
        except Exception:  # noqa: BLE001 - Firewall障害はfail closed、詳細は保存しない
            decision = FirewallDecision.BLOCK
        if decision == FirewallDecision.BLOCK:
            return (
                _failure("TOOL_FIREWALL_BLOCKED"),
                ToolExecutionStatus.BLOCKED,
                SecurityEventType.UNSAFE_EXTERNAL_ACTION,
                SecurityDetector.ORCAROUTER_FIREWALL,
            )
        result, status = await self._execute_with_retry(
            context, definition, validated_input, prepared
        )
        return result, status, None, None

    async def _execute_with_retry(
        self,
        context: TrustedToolContext,
        definition: ToolDefinition,
        validated_input: BaseModel,
        prepared: PreparedToolExecution,
    ) -> tuple[ToolResult, ToolExecutionStatus]:
        for attempt in range(self._ctx.settings.tool_max_attempts):
            remaining = self._remaining(context.turn_started_at)
            if remaining <= 0 or not await self._increment_attempt(prepared):
                return _failure("TOOL_TURN_ENDED"), ToolExecutionStatus.CANCELLED
            timeout = min(self._ctx.settings.tool_attempt_timeout_seconds, remaining)
            try:
                async with asyncio.timeout(timeout):
                    raw_output = await definition.handler.execute(context, validated_input)
                output = definition.output_model.model_validate(raw_output)
                data = mask_json(output.model_dump(mode="json"))
                return (
                    ToolResult(success=True, data=data, error=None),
                    ToolExecutionStatus.COMPLETED,
                )
            except TransientToolError:
                if attempt + 1 >= self._ctx.settings.tool_max_attempts:
                    return _failure("TOOL_RETRY_EXHAUSTED"), ToolExecutionStatus.FAILED
                delay = self._ctx.settings.tool_retry_backoff_seconds * (2**attempt)
                if delay >= self._remaining(context.turn_started_at):
                    return _failure("TOOL_RETRY_EXHAUSTED"), ToolExecutionStatus.FAILED
                await self._ctx.sleep(delay)
            except ValidationError:
                return _failure("TOOL_OUTPUT_INVALID"), ToolExecutionStatus.FAILED
            except ToolDomainError as error:
                result, status, _, _ = self._domain_failure(definition, error)
                return result, status
            except Exception:  # noqa: BLE001 - Tool詳細をResultやlogへ出さない
                return _failure("TOOL_EXECUTION_FAILED"), ToolExecutionStatus.FAILED
        return _failure("TOOL_RETRY_EXHAUSTED"), ToolExecutionStatus.FAILED

    def _remaining(self, started_at: datetime) -> float:
        elapsed = (self._ctx.clock.now() - started_at).total_seconds()
        return max(0.0, self._ctx.settings.turn_time_limit_seconds - elapsed)

    async def _trusted_context(self) -> TrustedToolContext | None:
        async with self._ctx.session_factory() as session:
            record = await ToolExecutionRepository(session).runtime_record(
                marketer_id=self._marketer_id,
                company_id=self._company_id,
                session_id=self._session_id,
                turn_id=self._turn_id,
            )
        if record is None:
            return None
        return TrustedToolContext(
            company_id=self._company_id,
            marketer_id=self._marketer_id,
            session_id=self._session_id,
            parent_session_id=record.parent_session_id,
            turn_id=self._turn_id,
            agent_type=record.agent_type,
            turn_status=record.turn_status,
            turn_started_at=record.started_at,
        )

    def _validate_provenance(self, refs: tuple[ToolProvenanceRef, ...]) -> bool:
        """Runner申告を構築済みContextの安全なmetadataだけで照合する。"""
        entries = {
            entry.item_id: entry
            for entry in self._agent_context.entries
            if entry.kind == "item" and entry.item_id is not None
        }
        seen: set[tuple[ToolProvenance, int | None]] = set()
        for ref in refs:
            key = (ref.source, ref.item_id)
            if key in seen:
                return False
            seen.add(key)
            if ref.source == ToolProvenance.SYSTEM:
                if ref.item_id is not None:
                    return False
                continue
            if ref.item_id is None:
                return False
            entry = entries.get(ref.item_id)
            if entry is None or entry.context_status != AgentItemContextStatus.ACTIVE:
                return False
            if not self._provenance_matches(ref.source, entry):
                return False
        return True

    @staticmethod
    def _provenance_matches(source: ToolProvenance, entry: AgentContextEntry) -> bool:
        if source == ToolProvenance.USER_INPUT:
            return (
                entry.role == "user"
                and entry.item_type == AgentItemType.USER_MESSAGE
                and entry.content_source == AgentContentSource.USER_INPUT
            )
        if source == ToolProvenance.TOOL_RESULT:
            return entry.role == "tool" and entry.item_type == AgentItemType.TOOL_RESULT
        if source == ToolProvenance.AGENT_CONTEXT:
            return (
                entry.role == "assistant"
                and entry.item_type in (AgentItemType.ASSISTANT_MESSAGE, AgentItemType.TOOL_CALL)
                and entry.content_source == AgentContentSource.AGENT_OUTPUT
            )
        return False

    @staticmethod
    def _domain_failure(
        definition: ToolDefinition, error: ToolDomainError
    ) -> tuple[ToolResult, ToolExecutionStatus, SecurityEventType | None, SecurityDetector | None]:
        """定義と完全一致する固定Errorだけを公開する。"""
        spec = definition.errors.get(error.code)
        if (
            spec is None
            or spec.message != error.message
            or spec.retryable != error.retryable
            or spec.blocked != error.blocked
        ):
            return _failure("TOOL_EXECUTION_FAILED"), ToolExecutionStatus.FAILED, None, None
        return (
            _failure(error.code, retryable=spec.retryable, message=spec.message),
            ToolExecutionStatus.BLOCKED if spec.blocked else ToolExecutionStatus.FAILED,
            SecurityEventType.UNAUTHORIZED_TOOL_CALL if spec.blocked else None,
            SecurityDetector.APPLICATION if spec.blocked else None,
        )

    async def _prepare(
        self,
        call: ToolCall,
        arguments: dict[str, Any],
        provenance: list[dict[str, Any]],
    ) -> PreparedToolExecution | None:
        async with self._ctx.session_factory() as session, session.begin():
            return await ToolExecutionRepository(session).prepare(
                turn_id=self._turn_id,
                stable_key=call.stable_key,
                name=call.name,
                arguments=arguments,
                provenance=provenance,
                now=self._ctx.clock.now(),
            )

    async def _claim(self, prepared: PreparedToolExecution) -> bool:
        async with self._ctx.session_factory() as session, session.begin():
            return await ToolExecutionRepository(session).claim(
                prepared.execution.id, self._turn_id
            )

    async def _increment_attempt(self, prepared: PreparedToolExecution) -> bool:
        async with self._ctx.session_factory() as session, session.begin():
            return await ToolExecutionRepository(session).increment_attempt(
                prepared.execution.id, self._turn_id
            )

    async def _terminal(self, prepared: PreparedToolExecution) -> ToolResult | None:
        async with self._ctx.session_factory() as session:
            item = await ToolExecutionRepository(session).terminal_result(
                self._turn_id, prepared.tool_call.id
            )
        return ToolResult.model_validate(item.content) if item is not None else None

    async def _terminal_by_key(
        self,
        call: ToolCall,
        arguments: dict[str, Any],
        provenance: list[dict[str, Any]],
    ) -> ToolResult | None:
        async with self._ctx.session_factory() as session:
            item = await ToolExecutionRepository(session).terminal_result_by_key(
                self._turn_id,
                call.stable_key,
                name=call.name,
                arguments=arguments,
                provenance=provenance,
            )
        return ToolResult.model_validate(item.content) if item is not None else None

    async def _finish(
        self,
        prepared: PreparedToolExecution,
        result: ToolResult,
        status: ToolExecutionStatus,
        source: AgentContentSource,
        context_class: AgentContextClass,
        event_type: SecurityEventType | None,
        detector: SecurityDetector | None,
    ) -> bool:
        async with self._ctx.session_factory() as session, session.begin():
            item = await ToolExecutionRepository(session).finish(
                turn_id=self._turn_id,
                tool_call_item_id=prepared.tool_call.id,
                execution_id=prepared.execution.id,
                result=result.model_dump(mode="json"),
                status=status,
                source=source,
                context_class=context_class,
                now=self._ctx.clock.now(),
                event_type=event_type,
                detector=detector,
            )
            return item is not None

    def _activity_started(self, name: str, parent_activity_id: str | None) -> str:
        try:
            return self._reporter.activity_started("tool", name, parent_activity_id)
        except Exception:  # noqa: BLE001 - 進捗通知は実行結果へ影響させない
            return ""

    def _activity_finished(self, activity_id: str, status: ActivityStatus) -> None:
        with suppress(Exception):
            self._reporter.activity_finished(activity_id, status)
