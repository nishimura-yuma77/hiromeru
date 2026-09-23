from collections.abc import AsyncIterator, Mapping
from dataclasses import replace

from sqlalchemy import select

from agent_runtime.executor import ToolExecutor
from agent_runtime.firewall import FakeAgentFirewall
from agent_runtime.guardrail import FakeToolResultGuardrail, GuardrailDecision
from agent_runtime.tools import ToolCall
from agent_runtime.web_tools import WebFetchHandler, WebSearchHandler
from api.sse import NullReporter
from clients.web_fetch import PinnedResponse, ResolvedUrl, SafeWebFetcher
from clients.web_search import ProviderSearchResult
from domain.enums import AgentItemContextStatus, AgentItemType, AgentTurnStatus
from models import AgentItem
from repositories.agent import SessionRepository, TurnRepository
from services.context import ServiceContext
from tests.support.client import Account


class Provider:
    async def search(self, query: str, limit: int) -> tuple[ProviderSearchResult, ...]:
        del query, limit
        return (
            ProviderSearchResult(
                title="Example", url="https://93.184.216.34/page", snippet="result"
            ),
        )


async def _chunks() -> AsyncIterator[bytes]:
    yield b"Fetched user@example.com"


async def _close() -> None:
    return None


class Transport:
    def __init__(self) -> None:
        self.requests: list[tuple[ResolvedUrl, Mapping[str, str]]] = []

    async def request(self, target: ResolvedUrl, headers: Mapping[str, str]) -> PinnedResponse:
        self.requests.append((target, headers))
        return PinnedResponse(200, {"content-type": "text/plain"}, _chunks(), _close)


async def _turn(
    account: Account, ctx: ServiceContext, session_id: int | None = None
) -> ToolExecutor:
    selected_session = session_id or await account.create_session()
    async with ctx.session_factory() as session, session.begin():
        locked = await SessionRepository(session).get_parent(
            account.marketer_id, selected_session, lock=True
        )
        assert locked is not None
        turn = await TurnRepository(session).create_turn(selected_session, ctx.clock.now())
    return ToolExecutor(
        ctx,
        marketer_id=account.marketer_id,
        company_id=account.company_id,
        session_id=selected_session,
        turn_id=turn.id,
        reporter=NullReporter(),
    )


def _configure(ctx: ServiceContext, transport: Transport) -> None:
    search = ctx.tool_registry.get("web_search")
    fetch = ctx.tool_registry.get("web_fetch")
    assert search is not None and isinstance(search.handler, WebSearchHandler)
    assert fetch is not None and isinstance(fetch.handler, WebFetchHandler)
    search.handler._deps = replace(search.handler._deps, search_provider=Provider())
    fetch.handler._deps = replace(
        fetch.handler._deps,
        fetcher=SafeWebFetcher(
            resolver=fetch.handler._deps.fetcher._resolver,
            transport=transport,
            max_bytes=1_000,
            max_redirects=2,
        ),
    )


async def test_same_turn_result_idだけを解決しpreflightをFirewallへ渡す(
    account: Account, ctx: ServiceContext
) -> None:
    transport = Transport()
    _configure(ctx, transport)
    executor = await _turn(account, ctx)
    direct = await executor.invoke(
        ToolCall(
            name="web_fetch",
            stable_key="direct-url",
            arguments={
                "search_result_id": "0" * 32,
                "url": "https://example.com",
            },
        )
    )
    assert direct.error is not None and direct.error.code == "INVALID_ARGUMENT"
    searched = await executor.invoke(
        ToolCall(name="web_search", stable_key="search", arguments={"query": "x", "limit": 1})
    )
    assert searched.data is not None
    result_id = searched.data["results"][0]["search_result_id"]

    fetched = await executor.invoke(
        ToolCall(
            name="web_fetch",
            stable_key="fetch",
            arguments={"search_result_id": result_id},
        )
    )

    assert fetched.data == {
        "search_result_id": result_id,
        "url": "https://93.184.216.34/page",
        "content": "Fetched [EMAIL]",
    }
    assert len(transport.requests) == 1
    firewall = ctx.agent_firewall
    assert isinstance(firewall, FakeAgentFirewall)
    preflight = firewall.requests[-1].masked_arguments
    assert preflight["search_result_id"] == result_id
    assert preflight["resolved_url"] == "https://93.184.216.34/page"
    assert isinstance(preflight["search_result_item_id"], int)

    async with ctx.session_factory() as session, session.begin():
        item = await session.get(AgentItem, preflight["search_result_item_id"])
        assert item is not None
        malformed = dict(item.content)
        malformed["data"] = {"results": [{"search_result_id": result_id, "url": 123}]}
        item.content = malformed
    rejected = await executor.invoke(
        ToolCall(
            name="web_fetch",
            stable_key="malformed-result",
            arguments={"search_result_id": result_id},
        )
    )
    assert rejected.error is not None and rejected.error.code == "URL_NOT_ALLOWED"
    assert len(transport.requests) == 1


async def test_result_idは別turnとquarantined_resultから再利用できない(
    account: Account, ctx: ServiceContext
) -> None:
    transport = Transport()
    _configure(ctx, transport)
    first = await _turn(account, ctx)
    searched = await first.invoke(
        ToolCall(name="web_search", stable_key="search", arguments={"query": "x", "limit": 1})
    )
    assert searched.data is not None
    result_id = searched.data["results"][0]["search_result_id"]
    async with ctx.session_factory() as session, session.begin():
        await TurnRepository(session).finish_turn(
            first._turn_id, status=AgentTurnStatus.COMPLETED, now=ctx.clock.now()
        )
    second = await _turn(account, ctx, first._session_id)
    reused = await second.invoke(
        ToolCall(
            name="web_fetch", stable_key="other-turn", arguments={"search_result_id": result_id}
        )
    )
    assert reused.error is not None and reused.error.code == "URL_NOT_ALLOWED"
    assert transport.requests == []

    guardrail = ctx.tool_result_guardrail
    assert isinstance(guardrail, FakeToolResultGuardrail)
    guardrail.decision = GuardrailDecision.BLOCK
    quarantined = await second.invoke(
        ToolCall(name="web_search", stable_key="quarantined", arguments={"query": "x", "limit": 1})
    )
    assert quarantined.error is not None
    async with ctx.session_factory() as session:
        item = (
            await session.execute(
                select(AgentItem).where(
                    AgentItem.agent_turn_id == second._turn_id,
                    AgentItem.item_type == AgentItemType.TOOL_RESULT,
                    AgentItem.context_status == AgentItemContextStatus.QUARANTINED,
                )
            )
        ).scalar_one()
    quarantined_id = item.content["data"]["results"][0]["search_result_id"]
    async with ctx.session_factory() as session:
        repository = TurnRepository(session)
        turn = await repository.get_turn(second._session_id, second._turn_id)
        assert turn is not None
        bundle = (await repository.bundles([turn]))[0]
    assert item.id not in {visible.id for visible in bundle.items}
    guardrail.decision = GuardrailDecision.ALLOW
    rejected = await second.invoke(
        ToolCall(
            name="web_fetch",
            stable_key="quarantined-fetch",
            arguments={"search_result_id": quarantined_id},
        )
    )
    assert rejected.error is not None and rejected.error.code == "URL_NOT_ALLOWED"
    assert transport.requests == []
