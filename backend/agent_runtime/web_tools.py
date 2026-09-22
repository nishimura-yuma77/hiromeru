"""Web検索・安全なWeb取得Agent Tool。"""
# ruff: noqa: D101, D102

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Never, cast

from pydantic import Field, ValidationError, field_validator
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_runtime.tools import (
    StrictToolModel,
    ToolDefinition,
    ToolDomainError,
    ToolErrorSpec,
    ToolHandler,
    ToolPreparation,
    ToolRegistry,
    TrustedToolContext,
)
from clients.web_fetch import (
    ContentTooLargeError,
    ResolvedUrl,
    SafeWebFetcher,
    UnsafeUrlError,
    WebFetchError,
)
from clients.web_search import ProviderSearchResult, WebSearchProvider, WebSearchProviderError
from core.masking import mask_text
from domain.enums import AgentContentSource, AgentContextClass, AgentType
from repositories.agent import ToolExecutionRepository

_ALL_AGENTS = frozenset({AgentType.PARENT, AgentType.CAMPAIGN_PLANNER, AgentType.CONTENT_CREATOR})


@dataclass(frozen=True)
class WebToolDependencies:
    session_factory: async_sessionmaker[AsyncSession]
    search_provider: WebSearchProvider
    fetcher: SafeWebFetcher
    new_uuid: Callable[[], uuid.UUID]


class WebSearchInput(StrictToolModel):
    query: str = Field(min_length=1, max_length=4_000)
    limit: int = Field(gt=0, le=20)

    @field_validator("query")
    @classmethod
    def _query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be blank")
        return value.strip()


class WebSearchResult(StrictToolModel):
    search_result_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    title: str
    url: str
    snippet: str


class WebSearchOutput(StrictToolModel):
    results: tuple[WebSearchResult, ...]


class WebFetchInput(StrictToolModel):
    search_result_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class WebFetchOutput(StrictToolModel):
    search_result_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    url: str
    content: str


@dataclass(frozen=True)
class _FetchPrepared:
    search_result_id: str
    search_result_item_id: int
    target: ResolvedUrl


_ERRORS: Mapping[str, ToolErrorSpec] = {
    "INVALID_ARGUMENT": ToolErrorSpec("The tool input is invalid."),
    "URL_NOT_ALLOWED": ToolErrorSpec("The search result is not available for this turn."),
    "UNSAFE_URL": ToolErrorSpec("The search result URL is not safe to fetch.", blocked=True),
    "CONTENT_TOO_LARGE": ToolErrorSpec("The web content exceeds the allowed size."),
    "WEB_FETCH_FAILED": ToolErrorSpec("The web content could not be fetched.", True),
    "WEB_SEARCH_FAILED": ToolErrorSpec("The web search could not be completed.", True),
}


def _raise(code: str) -> Never:
    spec = _ERRORS[code]
    raise ToolDomainError(code, spec.message, retryable=spec.retryable, blocked=spec.blocked)


class WebSearchHandler:
    def __init__(self, dependencies: WebToolDependencies) -> None:
        """依存を保持する。"""
        self._deps = dependencies

    async def authorize(self, context: TrustedToolContext, tool_input: WebSearchInput) -> bool:
        del context, tool_input
        return True

    async def execute(
        self, context: TrustedToolContext, tool_input: WebSearchInput
    ) -> WebSearchOutput:
        del context
        try:
            raw_rows = await self._deps.search_provider.search(
                mask_text(tool_input.query), tool_input.limit
            )
            if len(raw_rows) > tool_input.limit:
                raise ValueError
            rows = tuple(ProviderSearchResult.model_validate(row) for row in raw_rows)
        except (WebSearchProviderError, ValidationError, TypeError, ValueError, AttributeError):
            _raise("WEB_SEARCH_FAILED")
        return WebSearchOutput(
            results=tuple(
                WebSearchResult(
                    search_result_id=self._deps.new_uuid().hex,
                    title=mask_text(row.title),
                    url=mask_text(row.url),
                    snippet=mask_text(row.snippet),
                )
                for row in rows
            )
        )


class WebFetchHandler:
    def __init__(self, dependencies: WebToolDependencies) -> None:
        """依存を保持する。"""
        self._deps = dependencies

    async def authorize(self, context: TrustedToolContext, tool_input: WebFetchInput) -> bool:
        del context, tool_input
        return True

    async def prepare(
        self, context: TrustedToolContext, tool_input: WebFetchInput
    ) -> ToolPreparation:
        try:
            async with self._deps.session_factory() as session:
                resolved = await ToolExecutionRepository(session).active_search_result(
                    turn_id=context.turn_id, search_result_id=tool_input.search_result_id
                )
        except SQLAlchemyError:
            _raise("WEB_FETCH_FAILED")
        if resolved is None:
            _raise("URL_NOT_ALLOWED")
        item_id, url = resolved
        try:
            target = await self._deps.fetcher.resolve(url)
        except UnsafeUrlError:
            _raise("UNSAFE_URL")
        except WebFetchError:
            _raise("WEB_FETCH_FAILED")
        prepared = _FetchPrepared(tool_input.search_result_id, item_id, target)
        return ToolPreparation(
            execution_input=prepared,
            masked_arguments={
                "search_result_id": tool_input.search_result_id,
                "search_result_item_id": item_id,
                "resolved_url": mask_text(target.url),
            },
        )

    async def execute(
        self, context: TrustedToolContext, tool_input: _FetchPrepared
    ) -> WebFetchOutput:
        del context
        try:
            final_url, content = await self._deps.fetcher.fetch(tool_input.target)
        except UnsafeUrlError:
            _raise("UNSAFE_URL")
        except ContentTooLargeError:
            _raise("CONTENT_TOO_LARGE")
        except WebFetchError:
            _raise("WEB_FETCH_FAILED")
        return WebFetchOutput(
            search_result_id=tool_input.search_result_id,
            url=mask_text(final_url),
            content=mask_text(content),
        )


def register_web_tools(registry: ToolRegistry, dependencies: WebToolDependencies) -> None:
    """既存Registryへ2つのWeb Toolを登録する。"""
    definitions = (
        (
            "web_search",
            WebSearchInput,
            WebSearchOutput,
            WebSearchHandler,
            AgentContentSource.WEB_SEARCH,
        ),
        (
            "web_fetch",
            WebFetchInput,
            WebFetchOutput,
            WebFetchHandler,
            AgentContentSource.WEB_CONTENT,
        ),
    )
    error_names = {
        "web_search": ("INVALID_ARGUMENT", "WEB_SEARCH_FAILED"),
        "web_fetch": (
            "INVALID_ARGUMENT",
            "URL_NOT_ALLOWED",
            "UNSAFE_URL",
            "CONTENT_TOO_LARGE",
            "WEB_FETCH_FAILED",
        ),
    }
    for name, input_model, output_model, handler, source in definitions:
        registry.register(
            ToolDefinition(
                name=name,
                input_model=input_model,
                output_model=output_model,
                handler=cast(ToolHandler, handler(dependencies)),
                allowed_agents=_ALL_AGENTS,
                result_source=source,
                result_context_class=AgentContextClass.UNTRUSTED_DATA,
                errors={code: _ERRORS[code] for code in error_names[name]},
            )
        )
