"""会社Dataと長期記憶を扱う既定Agent Tool。"""
# ruff: noqa: D101, D102

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Never, Self, cast

from pydantic import Field, JsonValue, field_validator, model_validator
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_runtime.tools import (
    StrictToolModel,
    ToolDefinition,
    ToolDomainError,
    ToolErrorSpec,
    ToolHandler,
    ToolProvenance,
    ToolRegistry,
    TrustedToolContext,
)
from clients.embedding import EmbeddingClient
from clients.errors import EmbeddingError
from core.clock import Clock
from core.config import Settings
from core.masking import mask_text
from domain.enums import (
    AgentContentSource,
    AgentContextClass,
    AgentItemContextStatus,
    AgentItemType,
    AgentType,
    PostMetricStatus,
)
from domain.metrics import EMPTY_SUMMARY, MetricsSummary
from domain.timefmt import format_utc, parse_aware_datetime
from models import Campaign, PostMetric, PostTrackingLink
from repositories.agent import TurnRepository
from repositories.campaigns import CampaignRepository
from repositories.memories import MemoryRepository
from repositories.posts import PostFilter, PostRepository, PostRow
from services.metrics_view import to_metrics_view

_ALL_AGENTS = frozenset({AgentType.PARENT, AgentType.CAMPAIGN_PLANNER, AgentType.CONTENT_CREATOR})
_PARENT = frozenset({AgentType.PARENT})
_REMEMBER = re.compile(r"(?:覚えて|記憶して)(?:おいて)?(?:ください)?[。.!！]?$")
_FORGET_COMMAND = r"(?:忘れて|削除して|消して)(?:ください)?[。.!！]?$"
_UTC_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{6})?Z$"


@dataclass(frozen=True)
class ToolHandlerDependencies:
    """Handler構築に必要な循環しない依存bundle。"""

    settings: Settings
    session_factory: async_sessionmaker[AsyncSession]
    embedding: EmbeddingClient
    clock: Clock


class _IdInput(StrictToolModel):
    """正整数ID入力の共通検証。"""


class GetCampaignInput(_IdInput):
    campaign_id: int = Field(gt=0)


class GetPostInput(_IdInput):
    post_id: int = Field(gt=0)


class GetSessionItemsInput(StrictToolModel):
    item_ids: list[int] = Field(min_length=1, max_length=100)

    @field_validator("item_ids")
    @classmethod
    def _valid_ids(cls, value: list[int]) -> list[int]:
        if any(item_id <= 0 for item_id in value) or len(set(value)) != len(value):
            raise ValueError("item_ids must contain unique positive integers")
        return value


class SearchMemoryInput(StrictToolModel):
    query: str = Field(min_length=1, max_length=4_000)
    limit: int = Field(gt=0, le=100)

    @field_validator("query")
    @classmethod
    def _query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be blank")
        return value.strip()


class SaveMemoryInput(StrictToolModel):
    source_item_id: int = Field(gt=0)
    content: str = Field(min_length=1, max_length=20_000)
    campaign_ids: list[int] = Field(default_factory=list, max_length=100)
    post_ids: list[int] = Field(default_factory=list, max_length=100)

    @field_validator("campaign_ids", "post_ids")
    @classmethod
    def _relations(cls, value: list[int]) -> list[int]:
        if any(item_id <= 0 for item_id in value) or len(set(value)) != len(value):
            raise ValueError("relation ids must be unique positive integers")
        return value


class DeleteMemoryInput(_IdInput):
    memory_id: int = Field(gt=0)


class _SearchInput(StrictToolModel):
    query: str = Field(min_length=1, max_length=4_000)
    limit: int = Field(gt=0, le=100)

    @field_validator("query")
    @classmethod
    def _query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be blank")
        return value.strip()


def _aware_range(start: str | None, end: str | None) -> tuple[datetime | None, datetime | None]:
    parsed_start = parse_aware_datetime(start) if start is not None else None
    parsed_end = parse_aware_datetime(end) if end is not None else None
    if parsed_start is not None and parsed_end is not None and parsed_start >= parsed_end:
        raise ValueError("datetime range must be increasing")
    return parsed_start, parsed_end


class SearchCampaignsInput(_SearchInput):
    created_from: str | None = Field(default=None, pattern=_UTC_PATTERN)
    created_to: str | None = Field(default=None, pattern=_UTC_PATTERN)

    @model_validator(mode="after")
    def _range(self) -> Self:
        _aware_range(self.created_from, self.created_to)
        return self


class SearchPostsInput(_SearchInput):
    campaign_id: int | None = Field(default=None, gt=0)
    published_from: str | None = Field(default=None, pattern=_UTC_PATTERN)
    published_to: str | None = Field(default=None, pattern=_UTC_PATTERN)

    @model_validator(mode="after")
    def _range(self) -> Self:
        _aware_range(self.published_from, self.published_to)
        return self


class GetMarketingMetricsInput(StrictToolModel):
    campaign_id: int | None = Field(default=None, gt=0)
    post_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _xor(self) -> Self:
        if (self.campaign_id is None) == (self.post_id is None):
            raise ValueError("exactly one metrics scope is required")
        return self


class MetricsSummaryOutput(StrictToolModel):
    post_count: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    pending_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    x_pv_count: int = Field(ge=0)
    landing_user_count: int = Field(ge=0)
    landing_rate: float | None


class MetricsOutput(StrictToolModel):
    status: PostMetricStatus
    scheduled_at: str = Field(pattern=_UTC_PATTERN)
    measured_at: str | None = Field(pattern=_UTC_PATTERN)
    x_pv_count: int | None = Field(default=None, ge=0)
    landing_user_count: int | None = Field(default=None, ge=0)


class CampaignOutput(StrictToolModel):
    campaign_id: int = Field(gt=0)
    title: str
    target_profile: str
    background: str
    objective: str
    plan: str
    created_at: str = Field(pattern=_UTC_PATTERN)
    updated_at: str = Field(pattern=_UTC_PATTERN)
    archived_at: str | None = Field(pattern=_UTC_PATTERN)
    metrics_summary: MetricsSummaryOutput
    similarity: float | None = Field(default=None, ge=-1, le=1)


class GetCampaignOutput(StrictToolModel):
    campaign: CampaignOutput


class SearchCampaignsOutput(StrictToolModel):
    campaigns: tuple[CampaignOutput, ...]


class TrackingOutput(StrictToolModel):
    landing_url: str
    utm_source: str
    utm_medium: str
    utm_campaign: str
    utm_content: str
    tracked_url: str


class PostOutput(StrictToolModel):
    post_id: int = Field(gt=0)
    campaign_id: int = Field(gt=0)
    campaign_title: str
    campaign_archived_at: str | None = Field(pattern=_UTC_PATTERN)
    body: str
    x_post_id: str
    published_at: str = Field(pattern=_UTC_PATTERN)
    tracking: TrackingOutput
    metrics: MetricsOutput
    similarity: float | None = Field(default=None, ge=-1, le=1)


class GetPostOutput(StrictToolModel):
    post: PostOutput


class SearchPostsOutput(StrictToolModel):
    posts: tuple[PostOutput, ...]


class SessionItemOutput(StrictToolModel):
    item_id: int = Field(gt=0)
    turn_id: int = Field(gt=0)
    item_type: AgentItemType
    content_source: AgentContentSource
    context_class: AgentContextClass
    content: dict[str, JsonValue]


class GetSessionItemsOutput(StrictToolModel):
    items: tuple[SessionItemOutput, ...]


class MemoryOutput(StrictToolModel):
    memory_id: int = Field(gt=0)
    content: str
    similarity: float = Field(ge=-1, le=1)
    campaign_ids: tuple[int, ...]
    post_ids: tuple[int, ...]


class SearchMemoryOutput(StrictToolModel):
    memories: tuple[MemoryOutput, ...]


class SaveMemoryOutput(StrictToolModel):
    memory_id: int = Field(gt=0)


class DeleteMemoryOutput(StrictToolModel):
    memory_id: int = Field(gt=0)
    deleted: bool


class MarketingMetricsOutput(StrictToolModel):
    campaign_id: int | None = Field(default=None, gt=0)
    post_id: int | None = Field(default=None, gt=0)
    summary: MetricsSummaryOutput | None = None
    metrics: MetricsOutput | None = None

    @model_validator(mode="after")
    def _matching_scope(self) -> Self:
        campaign = (
            self.campaign_id is not None
            and self.summary is not None
            and self.post_id is None
            and self.metrics is None
        )
        post = (
            self.post_id is not None
            and self.metrics is not None
            and self.campaign_id is None
            and self.summary is None
        )
        if campaign == post:
            raise ValueError("output metrics scope is invalid")
        return self


_ERRORS: Mapping[str, ToolErrorSpec] = {
    "INVALID_ARGUMENT": ToolErrorSpec("The tool input is invalid."),
    "ITEM_NOT_FOUND": ToolErrorSpec("The requested item was not found."),
    "MEMORY_SAVE_NOT_REQUESTED": ToolErrorSpec(
        "The user did not explicitly request that this be remembered.", blocked=True
    ),
    "RELATED_ENTITY_NOT_FOUND": ToolErrorSpec("A related entity was not found."),
    "EMBEDDING_FAILED": ToolErrorSpec("The search representation could not be generated.", True),
    "MEMORY_SAVE_FAILED": ToolErrorSpec("The memory could not be saved.", True),
    "MEMORY_NOT_FOUND": ToolErrorSpec("The requested memory was not found."),
    "MEMORY_DELETE_NOT_APPROVED": ToolErrorSpec(
        "The user did not explicitly approve this memory deletion.", blocked=True
    ),
    "MEMORY_DELETE_FAILED": ToolErrorSpec("The memory could not be deleted."),
    "MEMORY_SEARCH_FAILED": ToolErrorSpec("The memories could not be searched.", True),
    "CAMPAIGN_NOT_FOUND": ToolErrorSpec("The requested campaign was not found."),
    "CAMPAIGN_GET_FAILED": ToolErrorSpec("The campaign could not be loaded.", True),
    "CAMPAIGN_SEARCH_FAILED": ToolErrorSpec("The campaigns could not be searched.", True),
    "POST_NOT_FOUND": ToolErrorSpec("The requested post was not found."),
    "POST_GET_FAILED": ToolErrorSpec("The post could not be loaded.", True),
    "POST_SEARCH_FAILED": ToolErrorSpec("The posts could not be searched.", True),
    "METRICS_NOT_FOUND": ToolErrorSpec("The requested metrics target was not found."),
    "METRICS_QUERY_FAILED": ToolErrorSpec("The metrics could not be loaded.", True),
}


def _raise(code: str) -> Never:
    spec = _ERRORS[code]
    raise ToolDomainError(code, spec.message, retryable=spec.retryable, blocked=spec.blocked)


def _summary(value: MetricsSummary) -> MetricsSummaryOutput:
    return MetricsSummaryOutput(
        post_count=value.post_count,
        completed_count=value.completed_count,
        pending_count=value.pending_count,
        failed_count=value.failed_count,
        x_pv_count=value.x_pv_count,
        landing_user_count=value.landing_user_count,
        landing_rate=value.landing_rate,
    )


def _metric(value: PostMetric) -> MetricsOutput:
    view = to_metrics_view(value)
    return MetricsOutput(
        status=value.status,
        scheduled_at=format_utc(view.scheduled_at),
        measured_at=format_utc(view.measured_at) if view.measured_at is not None else None,
        x_pv_count=view.x_pv_count,
        landing_user_count=view.landing_user_count,
    )


def _campaign(
    value: Campaign, summary: MetricsSummary, similarity: float | None = None
) -> CampaignOutput:
    return CampaignOutput(
        campaign_id=value.id,
        title=value.title,
        target_profile=value.target_profile,
        background=value.background,
        objective=value.objective,
        plan=value.plan,
        created_at=format_utc(value.created_at),
        updated_at=format_utc(value.updated_at),
        archived_at=format_utc(value.archived_at) if value.archived_at is not None else None,
        metrics_summary=_summary(summary),
        similarity=similarity,
    )


def _post(row: PostRow, tracking: PostTrackingLink) -> PostOutput:
    value = row.post
    return PostOutput(
        post_id=value.id,
        campaign_id=value.campaign_id,
        campaign_title=row.campaign_title,
        campaign_archived_at=(
            format_utc(row.campaign_archived_at) if row.campaign_archived_at is not None else None
        ),
        body=value.body,
        x_post_id=value.x_post_id,
        published_at=format_utc(value.published_at),
        tracking=TrackingOutput(
            landing_url=tracking.landing_url,
            utm_source=tracking.utm_source,
            utm_medium=tracking.utm_medium,
            utm_campaign=tracking.utm_campaign,
            utm_content=tracking.utm_content,
            tracked_url=tracking.tracked_url,
        ),
        metrics=_metric(row.metric),
        similarity=row.similarity,
    )


class _Handler:
    def __init__(self, dependencies: ToolHandlerDependencies) -> None:
        self._deps = dependencies

    async def authorize(self, context: TrustedToolContext, tool_input: Any) -> bool:  # noqa: ANN401
        del context, tool_input
        return True


class _ParentHandler(_Handler):
    async def authorize(self, context: TrustedToolContext, tool_input: Any) -> bool:  # noqa: ANN401
        del tool_input
        return context.agent_type == AgentType.PARENT and context.parent_session_id is None


class GetSessionItemsHandler(_ParentHandler):
    async def execute(
        self, context: TrustedToolContext, tool_input: GetSessionItemsInput
    ) -> GetSessionItemsOutput:
        if len(tool_input.item_ids) > self._deps.settings.tool_session_item_limit:
            _raise("INVALID_ARGUMENT")
        async with self._deps.session_factory() as session:
            rows = await TurnRepository(session).checkpoint_source_items(
                context.session_id, context.turn_id, tool_input.item_ids
            )
        if rows is None:
            _raise("ITEM_NOT_FOUND")
        items = tuple(
            SessionItemOutput(
                item_id=item.id,
                turn_id=turn.id,
                item_type=item.item_type,
                content_source=item.content_source,
                context_class=item.context_class,
                content=cast(
                    dict[str, JsonValue],
                    item.context_override
                    if item.context_status == AgentItemContextStatus.QUARANTINED
                    else item.content,
                ),
            )
            for turn, item in rows
        )
        output = GetSessionItemsOutput(items=items)
        encoded = json.dumps(
            output.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")
        ).encode()
        if len(encoded) > self._deps.settings.tool_session_output_max_bytes:
            _raise("INVALID_ARGUMENT")
        return output


class SearchMemoryHandler(_Handler):
    async def execute(
        self, context: TrustedToolContext, tool_input: SearchMemoryInput
    ) -> SearchMemoryOutput:
        if tool_input.limit > self._deps.settings.tool_search_limit:
            _raise("INVALID_ARGUMENT")
        try:
            vector = await self._deps.embedding.embed(tool_input.query)
        except EmbeddingError:
            _raise("EMBEDDING_FAILED")
        try:
            async with self._deps.session_factory() as session:
                repository = MemoryRepository(session)
                rows = await repository.search(context.company_id, vector, None, tool_input.limit)
                relations = await repository.relations(context.company_id, [row.id for row in rows])
        except SQLAlchemyError:
            _raise("MEMORY_SEARCH_FAILED")
        return SearchMemoryOutput(
            memories=tuple(
                MemoryOutput(
                    memory_id=row.id,
                    content=row.content,
                    similarity=cast(float, row.similarity),
                    campaign_ids=tuple(item[0] for item in relations.campaigns.get(row.id, [])),
                    post_ids=tuple(item[0] for item in relations.posts.get(row.id, [])),
                )
                for row in rows
            )
        )


async def _relations_valid(
    session: AsyncSession,
    company_id: int,
    campaign_ids: list[int],
    post_ids: list[int],
) -> bool:
    campaigns = await CampaignRepository(session).references(company_id, list(campaign_ids))
    posts = await PostRepository(session).published_ids(company_id, tuple(post_ids))
    return len(campaigns) == len(campaign_ids) and len(posts) == len(post_ids)


class SaveMemoryHandler(_ParentHandler):
    async def execute(
        self, context: TrustedToolContext, tool_input: SaveMemoryInput
    ) -> SaveMemoryOutput:
        settings = self._deps.settings
        if (
            len(tool_input.content) > settings.tool_memory_content_max_length
            or len(tool_input.campaign_ids) + len(tool_input.post_ids)
            > settings.tool_memory_relation_limit
        ):
            _raise("INVALID_ARGUMENT")
        provenance_ids = {
            ref.item_id for ref in context.provenance if ref.source == ToolProvenance.USER_INPUT
        }
        if tool_input.source_item_id not in provenance_ids:
            _raise("MEMORY_SAVE_NOT_REQUESTED")
        async with self._deps.session_factory() as session:
            source = await TurnRepository(session).trusted_user_item(
                context.session_id, tool_input.source_item_id
            )
        text = source.content.get("text") if source is not None else None
        if not isinstance(text, str) or _REMEMBER.search(text) is None:
            _raise("MEMORY_SAVE_NOT_REQUESTED")
        masked = mask_text(tool_input.content.strip())
        if not masked:
            _raise("INVALID_ARGUMENT")
        async with self._deps.session_factory() as session:
            if not await _relations_valid(
                session,
                context.company_id,
                tool_input.campaign_ids,
                tool_input.post_ids,
            ):
                _raise("RELATED_ENTITY_NOT_FOUND")
        try:
            embedding = await self._deps.embedding.embed(masked)
        except EmbeddingError:
            _raise("EMBEDDING_FAILED")
        try:
            async with self._deps.session_factory() as session, session.begin():
                if not await _relations_valid(
                    session,
                    context.company_id,
                    tool_input.campaign_ids,
                    tool_input.post_ids,
                ):
                    _raise("RELATED_ENTITY_NOT_FOUND")
                memory = await MemoryRepository(session).insert(
                    context.company_id,
                    masked,
                    embedding,
                    tuple(tool_input.campaign_ids),
                    tuple(tool_input.post_ids),
                )
        except ToolDomainError:
            raise
        except SQLAlchemyError:
            _raise("MEMORY_SAVE_FAILED")
        return SaveMemoryOutput(memory_id=memory.id)


class DeleteMemoryHandler(_ParentHandler):
    async def execute(
        self, context: TrustedToolContext, tool_input: DeleteMemoryInput
    ) -> DeleteMemoryOutput:
        async with self._deps.session_factory() as session:
            if not await MemoryRepository(session).exists(context.company_id, tool_input.memory_id):
                _raise("MEMORY_NOT_FOUND")
        approved = False
        for ref in context.provenance:
            if ref.source != ToolProvenance.USER_INPUT or ref.item_id is None:
                continue
            async with self._deps.session_factory() as session:
                source = await TurnRepository(session).trusted_user_item(
                    context.session_id, ref.item_id
                )
            text = source.content.get("text") if source is not None else None
            if (
                isinstance(text, str)
                and re.search(rf"(?<!\d){tool_input.memory_id}(?!\d).*{_FORGET_COMMAND}", text)
                is not None
            ):
                approved = True
                break
        if not approved:
            _raise("MEMORY_DELETE_NOT_APPROVED")
        try:
            async with self._deps.session_factory() as session, session.begin():
                deleted = await MemoryRepository(session).delete(
                    context.company_id, tool_input.memory_id
                )
        except SQLAlchemyError:
            _raise("MEMORY_DELETE_FAILED")
        if not deleted:
            _raise("MEMORY_NOT_FOUND")
        return DeleteMemoryOutput(memory_id=tool_input.memory_id, deleted=True)


class GetCampaignHandler(_Handler):
    async def execute(
        self, context: TrustedToolContext, tool_input: GetCampaignInput
    ) -> GetCampaignOutput:
        try:
            async with self._deps.session_factory() as session:
                value = await CampaignRepository(session).get(
                    context.company_id, tool_input.campaign_id
                )
                if value is None:
                    _raise("CAMPAIGN_NOT_FOUND")
                summary = (
                    await PostRepository(session).summarize(
                        context.company_id, campaign_ids=[value.id]
                    )
                ).get(value.id, EMPTY_SUMMARY)
        except ToolDomainError:
            raise
        except SQLAlchemyError:
            _raise("CAMPAIGN_GET_FAILED")
        return GetCampaignOutput(campaign=_campaign(value, summary))


class SearchCampaignsHandler(_Handler):
    async def execute(
        self, context: TrustedToolContext, tool_input: SearchCampaignsInput
    ) -> SearchCampaignsOutput:
        if tool_input.limit > self._deps.settings.tool_search_limit:
            _raise("INVALID_ARGUMENT")
        try:
            vector = await self._deps.embedding.embed(tool_input.query)
        except EmbeddingError:
            _raise("EMBEDDING_FAILED")
        start, end = _aware_range(tool_input.created_from, tool_input.created_to)
        try:
            async with self._deps.session_factory() as session:
                rows = await CampaignRepository(session).search(
                    context.company_id,
                    vector,
                    created_from=start,
                    created_to=end,
                    archived=None,
                    limit=tool_input.limit,
                )
                summaries = await PostRepository(session).summarize(
                    context.company_id, campaign_ids=[value.id for value, _ in rows]
                )
        except SQLAlchemyError:
            _raise("CAMPAIGN_SEARCH_FAILED")
        return SearchCampaignsOutput(
            campaigns=tuple(
                _campaign(value, summaries.get(value.id, EMPTY_SUMMARY), similarity)
                for value, similarity in rows
            )
        )


async def _post_outputs(
    session: AsyncSession, repository: PostRepository, rows: list[PostRow]
) -> tuple[PostOutput, ...]:
    outputs = []
    for row in rows:
        tracking = await repository.get_tracking(row.post.id)
        if tracking is None:
            _raise("POST_NOT_FOUND")
        outputs.append(_post(row, tracking))
    return tuple(outputs)


class GetPostHandler(_Handler):
    async def execute(self, context: TrustedToolContext, tool_input: GetPostInput) -> GetPostOutput:
        try:
            async with self._deps.session_factory() as session:
                repository = PostRepository(session)
                row = await repository.get_published(context.company_id, tool_input.post_id)
                if row is None:
                    _raise("POST_NOT_FOUND")
                outputs = await _post_outputs(session, repository, [row])
        except ToolDomainError:
            raise
        except SQLAlchemyError:
            _raise("POST_GET_FAILED")
        return GetPostOutput(post=outputs[0])


class SearchPostsHandler(_Handler):
    async def execute(
        self, context: TrustedToolContext, tool_input: SearchPostsInput
    ) -> SearchPostsOutput:
        if tool_input.limit > self._deps.settings.tool_search_limit:
            _raise("INVALID_ARGUMENT")
        try:
            vector = await self._deps.embedding.embed(tool_input.query)
        except EmbeddingError:
            _raise("EMBEDDING_FAILED")
        start, end = _aware_range(tool_input.published_from, tool_input.published_to)
        try:
            async with self._deps.session_factory() as session:
                if (
                    tool_input.campaign_id is not None
                    and await CampaignRepository(session).get(
                        context.company_id, tool_input.campaign_id
                    )
                    is None
                ):
                    _raise("CAMPAIGN_NOT_FOUND")
                repository = PostRepository(session)
                rows = await repository.search_posts(
                    context.company_id,
                    vector,
                    PostFilter(tool_input.campaign_id, start, end),
                    tool_input.limit,
                )
                outputs = await _post_outputs(session, repository, rows)
        except ToolDomainError:
            raise
        except SQLAlchemyError:
            _raise("POST_SEARCH_FAILED")
        return SearchPostsOutput(posts=outputs)


class GetMarketingMetricsHandler(_Handler):
    async def execute(
        self, context: TrustedToolContext, tool_input: GetMarketingMetricsInput
    ) -> MarketingMetricsOutput:
        try:
            async with self._deps.session_factory() as session:
                posts = PostRepository(session)
                if tool_input.campaign_id is not None:
                    campaign = await CampaignRepository(session).get(
                        context.company_id, tool_input.campaign_id
                    )
                    if campaign is None:
                        _raise("METRICS_NOT_FOUND")
                    summary = (
                        await posts.summarize(
                            context.company_id, campaign_ids=[tool_input.campaign_id]
                        )
                    ).get(tool_input.campaign_id, EMPTY_SUMMARY)
                    return MarketingMetricsOutput(
                        campaign_id=tool_input.campaign_id, summary=_summary(summary)
                    )
                row = await posts.get_published(context.company_id, cast(int, tool_input.post_id))
                if row is None:
                    _raise("METRICS_NOT_FOUND")
                return MarketingMetricsOutput(post_id=row.post.id, metrics=_metric(row.metric))
        except ToolDomainError:
            raise
        except SQLAlchemyError:
            _raise("METRICS_QUERY_FAILED")


def build_default_tool_registry(dependencies: ToolHandlerDependencies) -> ToolRegistry:
    """9つの業務Toolを登録した独立Registryを返す。"""
    registry = ToolRegistry()
    definitions = (
        (
            "get_session_items",
            GetSessionItemsInput,
            GetSessionItemsOutput,
            GetSessionItemsHandler,
            _PARENT,
            AgentContentSource.DATABASE,
            AgentContextClass.UNTRUSTED_DATA,
        ),
        (
            "search_long_term_memory",
            SearchMemoryInput,
            SearchMemoryOutput,
            SearchMemoryHandler,
            _ALL_AGENTS,
            AgentContentSource.LONG_TERM_MEMORY,
            AgentContextClass.UNTRUSTED_DATA,
        ),
        (
            "save_long_term_memory",
            SaveMemoryInput,
            SaveMemoryOutput,
            SaveMemoryHandler,
            _PARENT,
            AgentContentSource.DATABASE,
            AgentContextClass.CONVERSATION,
        ),
        (
            "delete_long_term_memory",
            DeleteMemoryInput,
            DeleteMemoryOutput,
            DeleteMemoryHandler,
            _PARENT,
            AgentContentSource.DATABASE,
            AgentContextClass.CONVERSATION,
        ),
        (
            "get_campaign",
            GetCampaignInput,
            GetCampaignOutput,
            GetCampaignHandler,
            _ALL_AGENTS,
            AgentContentSource.DATABASE,
            AgentContextClass.CONVERSATION,
        ),
        (
            "search_campaigns",
            SearchCampaignsInput,
            SearchCampaignsOutput,
            SearchCampaignsHandler,
            _ALL_AGENTS,
            AgentContentSource.DATABASE,
            AgentContextClass.CONVERSATION,
        ),
        (
            "get_post",
            GetPostInput,
            GetPostOutput,
            GetPostHandler,
            _ALL_AGENTS,
            AgentContentSource.DATABASE,
            AgentContextClass.CONVERSATION,
        ),
        (
            "search_posts",
            SearchPostsInput,
            SearchPostsOutput,
            SearchPostsHandler,
            _ALL_AGENTS,
            AgentContentSource.DATABASE,
            AgentContextClass.CONVERSATION,
        ),
        (
            "get_marketing_metrics",
            GetMarketingMetricsInput,
            MarketingMetricsOutput,
            GetMarketingMetricsHandler,
            _ALL_AGENTS,
            AgentContentSource.DATABASE,
            AgentContextClass.CONVERSATION,
        ),
    )
    error_names = {
        "get_session_items": ("INVALID_ARGUMENT", "ITEM_NOT_FOUND"),
        "search_long_term_memory": (
            "INVALID_ARGUMENT",
            "EMBEDDING_FAILED",
            "MEMORY_SEARCH_FAILED",
        ),
        "save_long_term_memory": (
            "INVALID_ARGUMENT",
            "MEMORY_SAVE_NOT_REQUESTED",
            "RELATED_ENTITY_NOT_FOUND",
            "EMBEDDING_FAILED",
            "MEMORY_SAVE_FAILED",
        ),
        "delete_long_term_memory": (
            "INVALID_ARGUMENT",
            "MEMORY_NOT_FOUND",
            "MEMORY_DELETE_NOT_APPROVED",
            "MEMORY_DELETE_FAILED",
        ),
        "get_campaign": ("INVALID_ARGUMENT", "CAMPAIGN_NOT_FOUND", "CAMPAIGN_GET_FAILED"),
        "search_campaigns": (
            "INVALID_ARGUMENT",
            "EMBEDDING_FAILED",
            "CAMPAIGN_SEARCH_FAILED",
        ),
        "get_post": ("INVALID_ARGUMENT", "POST_NOT_FOUND", "POST_GET_FAILED"),
        "search_posts": (
            "INVALID_ARGUMENT",
            "CAMPAIGN_NOT_FOUND",
            "EMBEDDING_FAILED",
            "POST_NOT_FOUND",
            "POST_SEARCH_FAILED",
        ),
        "get_marketing_metrics": (
            "INVALID_ARGUMENT",
            "METRICS_NOT_FOUND",
            "METRICS_QUERY_FAILED",
        ),
    }
    for name, input_model, output_model, handler, agents, source, context_class in definitions:
        registry.register(
            ToolDefinition(
                name=name,
                input_model=input_model,
                output_model=output_model,
                handler=cast(ToolHandler, handler(dependencies)),
                allowed_agents=agents,
                result_source=source,
                result_context_class=context_class,
                errors={code: _ERRORS[code] for code in error_names[name]},
            )
        )
    return registry
