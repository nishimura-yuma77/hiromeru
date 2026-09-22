"""使い捨て子Agentの起動と、監査済み提案の提示Tool。"""
# ruff: noqa: D101, D102

import asyncio
from dataclasses import dataclass
from typing import Any, Never, cast

from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from agent_runtime.executor import ToolExecutor
from agent_runtime.runner import (
    CampaignPlannerOutput,
    CampaignProposal,
    ChildRunInput,
    ContentCreatorOutput,
    XPostProposal,
)
from agent_runtime.tools import (
    StrictToolModel,
    ToolDefinition,
    ToolDomainError,
    ToolErrorSpec,
    ToolHandler,
    TrustedToolContext,
)
from core.canonical import canonical_json
from core.masking import mask_json
from domain.campaign_rules import CampaignContent, campaign_field_errors
from domain.constants import MAX_LANDING_URL_LENGTH
from domain.enums import (
    AgentContentSource,
    AgentContextClass,
    AgentItemContextStatus,
    AgentItemType,
    AgentTurnStatus,
    AgentType,
    ToolExecutionStatus,
)
from domain.timefmt import format_utc
from domain.tracking import build_tracking_url, is_valid_landing_url
from domain.x_text import contains_url, is_within_x_limit
from models import AgentItem, AgentSession, AgentTurn, ToolExecution
from repositories.agent import TurnRepository
from repositories.campaigns import CampaignRepository
from services.agent_context import AgentContextBuilder
from services.context import ServiceContext

_PARENT = frozenset({AgentType.PARENT})
_RUN_NAMES = ("run_campaign_planner", "run_content_creator")
_UTC_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{6})?Z$"

_ERRORS = {
    "INVALID_ARGUMENT": ToolErrorSpec("The tool input is invalid."),
    "INVALID_REQUEST_ITEM": ToolErrorSpec("The request item is not valid for this turn."),
    "SUBAGENT_LIMIT_EXCEEDED": ToolErrorSpec("The subagent limit for this turn was exceeded."),
    "INVALID_SUBAGENT_OUTPUT": ToolErrorSpec("The subagent returned an invalid result."),
    "SUBAGENT_FAILED": ToolErrorSpec("The subagent could not be completed."),
    "INVALID_PROPOSAL_SOURCE": ToolErrorSpec("The proposal source is not valid for this turn."),
    "INVALID_CAMPAIGN_PROPOSAL": ToolErrorSpec("The campaign proposal is invalid."),
    "INVALID_POST_PROPOSAL": ToolErrorSpec("The post proposal is invalid."),
    "CAMPAIGN_NOT_FOUND": ToolErrorSpec("The requested campaign was not found."),
    "CAMPAIGN_ARCHIVED": ToolErrorSpec("The requested campaign is archived."),
}


def _raise(code: str) -> Never:
    spec = _ERRORS[code]
    raise ToolDomainError(code, spec.message, retryable=False)


class RunCampaignPlannerInput(StrictToolModel):
    request_item_id: int = Field(gt=0)


class RunContentCreatorInput(RunCampaignPlannerInput):
    campaign_id: int = Field(gt=0)


class _RunOutput(StrictToolModel):
    child_session_id: int = Field(gt=0)
    missing_information: tuple[str, ...] | None = Field(default=None, min_length=1)


class RunCampaignPlannerOutput(_RunOutput):
    proposal: CampaignProposal | None = None

    @model_validator(mode="after")
    def _xor(self) -> "RunCampaignPlannerOutput":
        if (self.proposal is None) == (self.missing_information is None):
            raise ValueError("proposal and missing_information must be exclusive")
        return self


class RunContentCreatorOutput(_RunOutput):
    proposal: XPostProposal | None = None

    @model_validator(mode="after")
    def _xor(self) -> "RunContentCreatorOutput":
        if (self.proposal is None) == (self.missing_information is None):
            raise ValueError("proposal and missing_information must be exclusive")
        return self


class ProposeCampaignInput(CampaignProposal):
    """LLM入力には `expected_updated_at` を持たせない。"""


class ProposeCampaignOutput(ProposeCampaignInput):
    expected_updated_at: str | None = Field(default=None, pattern=_UTC_PATTERN)


class ProposeXPostInput(XPostProposal):
    """投稿案の実内容だけを受け取る。"""


class ProposeXPostOutput(ProposeXPostInput):
    """表示用の検証済み投稿案。"""


@dataclass(frozen=True)
class _ChildRecord:
    session_id: int
    turn_id: int
    request: dict[str, Any]


class _ParentHandler:
    def __init__(self, ctx: ServiceContext) -> None:
        self._ctx = ctx

    async def authorize(self, context: TrustedToolContext, tool_input: BaseModel) -> bool:
        del tool_input
        return context.agent_type == AgentType.PARENT and context.parent_session_id is None


class _RunChildHandler(_ParentHandler):
    agent_type: AgentType

    async def _create_child(
        self,
        context: TrustedToolContext,
        request_item_id: int,
        campaign_id: int | None,
    ) -> _ChildRecord:
        if self._remaining(context) <= 0:
            _raise("SUBAGENT_FAILED")
        now = self._ctx.clock.now()
        async with self._ctx.session_factory() as session, session.begin():
            parent_turn = (
                await session.execute(
                    select(AgentTurn)
                    .join(AgentSession, AgentSession.id == AgentTurn.session_id)
                    .where(
                        AgentTurn.id == context.turn_id,
                        AgentTurn.session_id == context.session_id,
                        AgentTurn.status == AgentTurnStatus.RUNNING,
                        AgentSession.id == context.session_id,
                        AgentSession.marketer_id == context.marketer_id,
                        AgentSession.agent == AgentType.PARENT,
                        AgentSession.parent_session_id.is_(None),
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if parent_turn is None:
                _raise("INVALID_REQUEST_ITEM")
            request_item = (
                await session.execute(
                    select(AgentItem).where(
                        AgentItem.id == request_item_id,
                        AgentItem.agent_turn_id == context.turn_id,
                        AgentItem.item_type == AgentItemType.USER_MESSAGE,
                        AgentItem.content_source == AgentContentSource.USER_INPUT,
                        AgentItem.context_status == AgentItemContextStatus.ACTIVE,
                    )
                )
            ).scalar_one_or_none()
            text = request_item.content.get("text") if request_item is not None else None
            if not isinstance(text, str):
                _raise("INVALID_REQUEST_ITEM")
            count = await session.scalar(
                select(func.count(AgentItem.id)).where(
                    AgentItem.agent_turn_id == context.turn_id,
                    AgentItem.item_type == AgentItemType.TOOL_CALL,
                    AgentItem.content["name"].as_string().in_(_RUN_NAMES),
                )
            )
            if int(count or 0) > self._ctx.settings.agent_subagent_max_per_turn:
                _raise("SUBAGENT_LIMIT_EXCEEDED")
            campaign = None
            if campaign_id is not None:
                campaign = await CampaignRepository(session).get(context.company_id, campaign_id)
                if campaign is None:
                    _raise("CAMPAIGN_NOT_FOUND")
                if campaign.archived_at is not None:
                    _raise("CAMPAIGN_ARCHIVED")
            child_session = AgentSession(
                marketer_id=context.marketer_id,
                parent_session_id=context.session_id,
                agent=self.agent_type,
                created_at=now,
                updated_at=now,
            )
            session.add(child_session)
            await session.flush()
            child_turn = await TurnRepository(session).create_turn(child_session.id, now)
            structured: dict[str, Any] = {
                "request_item_id": request_item_id,
                "request": text,
            }
            if campaign is not None:
                structured["campaign"] = {
                    "id": campaign.id,
                    "title": campaign.title,
                    "target_profile": campaign.target_profile,
                    "background": campaign.background,
                    "objective": campaign.objective,
                    "plan": campaign.plan,
                }
            structured = cast(dict[str, Any], mask_json(structured))
            await TurnRepository(session).append_item(
                child_turn.id,
                key="child-input",
                item_type=AgentItemType.USER_MESSAGE,
                source=AgentContentSource.SYSTEM,
                content={"request": structured},
                now=now,
            )
            return _ChildRecord(child_session.id, child_turn.id, structured)

    async def _run_child(
        self,
        context: TrustedToolContext,
        record: _ChildRecord,
        *,
        expected_campaign_id: int | None = None,
    ) -> CampaignPlannerOutput | ContentCreatorOutput:
        try:
            return await self._run_child_inner(
                context,
                record,
                expected_campaign_id=expected_campaign_id,
            )
        except asyncio.CancelledError:
            await asyncio.shield(self._fail_child(record.turn_id))
            raise

    async def _run_child_inner(
        self,
        context: TrustedToolContext,
        record: _ChildRecord,
        *,
        expected_campaign_id: int | None,
    ) -> CampaignPlannerOutput | ContentCreatorOutput:
        if self._remaining(context) <= 0:
            await self._fail_child(record.turn_id)
            _raise("SUBAGENT_FAILED")
        try:
            child_context = await AgentContextBuilder(self._ctx).build(
                record.session_id, record.turn_id
            )
        except Exception:  # noqa: BLE001 - 子内部の構築失敗を固定Errorへ変換する
            await self._fail_child(record.turn_id)
            _raise("SUBAGENT_FAILED")
        if self._remaining(context) <= 0:
            await self._fail_child(record.turn_id)
            _raise("SUBAGENT_FAILED")
        child_executor = ToolExecutor(
            self._ctx,
            marketer_id=context.marketer_id,
            company_id=context.company_id,
            session_id=record.session_id,
            turn_id=record.turn_id,
            reporter=_NullReporter(),
            agent_context=child_context,
            budget_started_at=context.turn_started_at,
        )
        try:
            raw = await self._ctx.agent_runner.run_child(
                ChildRunInput(
                    agent_type=self.agent_type,
                    session_id=record.session_id,
                    turn_id=record.turn_id,
                    parent_session_id=context.session_id,
                    parent_turn_id=context.turn_id,
                    marketer_id=context.marketer_id,
                    company_id=context.company_id,
                    request=cast(dict[str, Any], record.request),
                    context=child_context,
                    tools=child_executor,
                    parent_started_at=context.turn_started_at,
                ),
                _NullReporter(),
            )
        except Exception:  # noqa: BLE001 - 子Runnerの内部詳細を親へ公開しない
            await self._fail_child(record.turn_id)
            _raise("SUBAGENT_FAILED")
        expected = (
            CampaignPlannerOutput
            if self.agent_type == AgentType.CAMPAIGN_PLANNER
            else ContentCreatorOutput
        )
        if not isinstance(raw, expected):
            await self._fail_child(record.turn_id)
            _raise("INVALID_SUBAGENT_OUTPUT")
        try:
            output = expected.model_validate(raw.model_dump(mode="python"))
            if (
                isinstance(output, ContentCreatorOutput)
                and output.proposal is not None
                and output.proposal.campaign_id != expected_campaign_id
            ):
                raise ValueError
            encoded = canonical_json(output.model_dump(mode="json")).encode("utf-8")
        except (ValidationError, TypeError, ValueError):
            await self._fail_child(record.turn_id)
            _raise("INVALID_SUBAGENT_OUTPUT")
        if len(encoded) > self._ctx.settings.subagent_final_output_max_bytes:
            await self._fail_child(record.turn_id)
            _raise("INVALID_SUBAGENT_OUTPUT")
        now = self._ctx.clock.now()
        completed = False
        async with self._ctx.session_factory() as session, session.begin():
            turns = TurnRepository(session)
            item = await turns.append_item_if_running(
                record.turn_id,
                key="child-final",
                item_type=AgentItemType.ASSISTANT_MESSAGE,
                source=AgentContentSource.AGENT_OUTPUT,
                content=cast(dict[str, Any], mask_json(output.model_dump(mode="json"))),
                now=now,
            )
            if item is not None:
                completed = await turns.finish_turn(
                    record.turn_id, status=AgentTurnStatus.COMPLETED, now=now
                )
        if not completed:
            await self._fail_child(record.turn_id)
            _raise("SUBAGENT_FAILED")
        return output

    async def _fail_child(self, turn_id: int) -> None:
        async with self._ctx.session_factory() as session, session.begin():
            await TurnRepository(session).finish_turn(
                turn_id,
                status=AgentTurnStatus.FAILED,
                now=self._ctx.clock.now(),
                error_code="SUBAGENT_FAILED",
                error_message=_ERRORS["SUBAGENT_FAILED"].message,
            )

    def _remaining(self, context: TrustedToolContext) -> float:
        elapsed = (self._ctx.clock.now() - context.turn_started_at).total_seconds()
        return self._ctx.settings.turn_time_limit_seconds - elapsed


class RunCampaignPlannerHandler(_RunChildHandler):
    agent_type = AgentType.CAMPAIGN_PLANNER

    async def execute(
        self, context: TrustedToolContext, tool_input: RunCampaignPlannerInput
    ) -> RunCampaignPlannerOutput:
        record = await self._create_child(context, tool_input.request_item_id, None)
        output = await self._run_child(context, record)
        if not isinstance(output, CampaignPlannerOutput):
            _raise("INVALID_SUBAGENT_OUTPUT")
        return RunCampaignPlannerOutput(
            child_session_id=record.session_id,
            proposal=output.proposal,
            missing_information=output.missing_information,
        )


class RunContentCreatorHandler(_RunChildHandler):
    agent_type = AgentType.CONTENT_CREATOR

    async def execute(
        self, context: TrustedToolContext, tool_input: RunContentCreatorInput
    ) -> RunContentCreatorOutput:
        record = await self._create_child(
            context, tool_input.request_item_id, tool_input.campaign_id
        )
        output = await self._run_child(
            context, record, expected_campaign_id=tool_input.campaign_id
        )
        if not isinstance(output, ContentCreatorOutput):
            _raise("INVALID_SUBAGENT_OUTPUT")
        return RunContentCreatorOutput(
            child_session_id=record.session_id,
            proposal=output.proposal,
            missing_information=output.missing_information,
        )


class _ProposalHandler(_ParentHandler):
    async def _source_matches(
        self,
        turn_id: int,
        tool_name: str,
        output_model: type[RunCampaignPlannerOutput] | type[RunContentCreatorOutput],
        proposal: dict[str, Any],
    ) -> bool:
        call = aliased(AgentItem)
        async with self._ctx.session_factory() as session:
            results = (
                await session.execute(
                    select(AgentItem)
                    .join(call, call.id == AgentItem.related_tool_call_item_id)
                    .join(ToolExecution, ToolExecution.tool_call_item_id == call.id)
                    .where(
                        AgentItem.agent_turn_id == turn_id,
                        AgentItem.item_type == AgentItemType.TOOL_RESULT,
                        AgentItem.context_status == AgentItemContextStatus.ACTIVE,
                        call.agent_turn_id == turn_id,
                        call.item_type == AgentItemType.TOOL_CALL,
                        call.content["name"].as_string() == tool_name,
                        ToolExecution.status == ToolExecutionStatus.COMPLETED,
                    )
                )
            ).scalars()
            for item in results:
                data = item.content.get("data") if item.content.get("success") is True else None
                if not isinstance(data, dict):
                    continue
                try:
                    parsed = output_model.model_validate(data)
                except ValidationError:
                    continue
                if (
                    parsed.proposal is not None
                    and parsed.proposal.model_dump(mode="json") == proposal
                ):
                    return True
        return False

    async def _campaign(self, company_id: int, campaign_id: int) -> Any:  # noqa: ANN401
        async with self._ctx.session_factory() as session:
            campaign = await CampaignRepository(session).get(company_id, campaign_id)
        if campaign is None:
            _raise("CAMPAIGN_NOT_FOUND")
        if campaign.archived_at is not None:
            _raise("CAMPAIGN_ARCHIVED")
        return campaign


class ProposeCampaignHandler(_ProposalHandler):
    async def execute(
        self, context: TrustedToolContext, tool_input: ProposeCampaignInput
    ) -> ProposeCampaignOutput:
        proposal = tool_input.model_dump(mode="json")
        if not await self._source_matches(
            context.turn_id, "run_campaign_planner", RunCampaignPlannerOutput, proposal
        ):
            _raise("INVALID_PROPOSAL_SOURCE")
        campaign = None
        if tool_input.id is not None:
            campaign = await self._campaign(context.company_id, tool_input.id)
        content = CampaignContent(
            tool_input.title,
            tool_input.target_profile,
            tool_input.background,
            tool_input.objective,
            tool_input.plan,
        )
        if campaign_field_errors(content):
            _raise("INVALID_CAMPAIGN_PROPOSAL")
        return ProposeCampaignOutput(
            **proposal,
            expected_updated_at=(format_utc(campaign.updated_at) if campaign is not None else None),
        )


class ProposeXPostHandler(_ProposalHandler):
    async def execute(
        self, context: TrustedToolContext, tool_input: ProposeXPostInput
    ) -> ProposeXPostOutput:
        proposal = tool_input.model_dump(mode="json")
        if not await self._source_matches(
            context.turn_id, "run_content_creator", RunContentCreatorOutput, proposal
        ):
            _raise("INVALID_PROPOSAL_SOURCE")
        await self._campaign(context.company_id, tool_input.campaign_id)
        tracking = build_tracking_url(tool_input.landing_url, tool_input.campaign_id, "proposal")
        if (
            contains_url(tool_input.body)
            or not is_valid_landing_url(tool_input.landing_url)
            or len(tracking.tracked_url) > MAX_LANDING_URL_LENGTH
            or not is_within_x_limit(f"{tool_input.body}\n{tracking.tracked_url}")
        ):
            _raise("INVALID_POST_PROPOSAL")
        return ProposeXPostOutput.model_validate(proposal)


class _NullReporter:
    def activity_started(
        self, kind: str, name: str, parent_activity_id: str | None = None
    ) -> str:
        del kind, name, parent_activity_id
        return ""

    def activity_finished(self, activity_id: str, status: str) -> None:
        del activity_id, status


def register_proposal_tools(ctx: ServiceContext) -> None:
    """4つの子Agent・提案Toolを既存Registryへ追加する。"""
    definitions = (
        (
            "run_campaign_planner",
            RunCampaignPlannerInput,
            RunCampaignPlannerOutput,
            RunCampaignPlannerHandler(ctx),
            (
                "INVALID_ARGUMENT",
                "INVALID_REQUEST_ITEM",
                "SUBAGENT_LIMIT_EXCEEDED",
                "INVALID_SUBAGENT_OUTPUT",
                "SUBAGENT_FAILED",
            ),
            False,
        ),
        (
            "run_content_creator",
            RunContentCreatorInput,
            RunContentCreatorOutput,
            RunContentCreatorHandler(ctx),
            (
                "INVALID_ARGUMENT",
                "INVALID_REQUEST_ITEM",
                "SUBAGENT_LIMIT_EXCEEDED",
                "INVALID_SUBAGENT_OUTPUT",
                "SUBAGENT_FAILED",
                "CAMPAIGN_NOT_FOUND",
                "CAMPAIGN_ARCHIVED",
            ),
            False,
        ),
        (
            "propose_campaign",
            ProposeCampaignInput,
            ProposeCampaignOutput,
            ProposeCampaignHandler(ctx),
            (
                "INVALID_ARGUMENT",
                "INVALID_PROPOSAL_SOURCE",
                "INVALID_CAMPAIGN_PROPOSAL",
                "CAMPAIGN_NOT_FOUND",
                "CAMPAIGN_ARCHIVED",
            ),
            True,
        ),
        (
            "propose_x_post",
            ProposeXPostInput,
            ProposeXPostOutput,
            ProposeXPostHandler(ctx),
            (
                "INVALID_ARGUMENT",
                "INVALID_PROPOSAL_SOURCE",
                "INVALID_POST_PROPOSAL",
                "CAMPAIGN_NOT_FOUND",
                "CAMPAIGN_ARCHIVED",
            ),
            True,
        ),
    )
    for name, input_model, output_model, handler, errors, terminal in definitions:
        ctx.tool_registry.register(
            ToolDefinition(
                name=name,
                input_model=input_model,
                output_model=output_model,
                handler=cast(ToolHandler, handler),
                allowed_agents=_PARENT,
                result_source=AgentContentSource.AGENT_OUTPUT,
                result_context_class=AgentContextClass.CONVERSATION,
                errors={code: _ERRORS[code] for code in errors},
                terminal=terminal,
                input_error_code=(
                    "INVALID_CAMPAIGN_PROPOSAL"
                    if name == "propose_campaign"
                    else "INVALID_POST_PROPOSAL"
                    if name == "propose_x_post"
                    else "INVALID_ARGUMENT"
                ),
                uses_remaining_turn_time=name in _RUN_NAMES,
            )
        )
