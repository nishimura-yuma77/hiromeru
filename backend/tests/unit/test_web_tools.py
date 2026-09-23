import uuid
from typing import Any, cast

import pytest
from pydantic import ValidationError

from agent_runtime.tools import ToolDomainError, TrustedToolContext
from agent_runtime.web_tools import (
    WebFetchInput,
    WebSearchHandler,
    WebSearchInput,
    WebToolDependencies,
)
from clients.web_fetch import SafeWebFetcher
from clients.web_search import ProviderSearchResult, WebSearchProviderError
from domain.enums import AgentTurnStatus, AgentType
from tests.support.fakes import FixedClock


class Provider:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.calls: list[tuple[str, int]] = []

    async def search(self, query: str, limit: int) -> Any:
        self.calls.append((query, limit))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _context() -> TrustedToolContext:
    clock = FixedClock()
    return TrustedToolContext(
        company_id=1,
        marketer_id=1,
        session_id=1,
        turn_id=1,
        agent_type=AgentType.PARENT,
        turn_status=AgentTurnStatus.RUNNING,
        turn_started_at=clock.now(),
    )


def _handler(provider: Provider) -> WebSearchHandler:
    dependencies = WebToolDependencies(
        session_factory=cast(Any, None),
        search_provider=provider,
        fetcher=cast(SafeWebFetcher, None),
        new_uuid=lambda: uuid.UUID(int=1),
    )
    return WebSearchHandler(dependencies)


async def test_search_inputとprovider_outputをmaskする() -> None:
    provider = Provider(
        (
            ProviderSearchResult(
                title="user@example.com",
                url="https://example.com/?token=secret-value",
                snippet="contact user@example.com",
            ),
        )
    )
    output = await _handler(provider).execute(
        _context(), WebSearchInput(query="find user@example.com", limit=1)
    )
    assert provider.calls == [("find [EMAIL]", 1)]
    assert output.results[0].title == "[EMAIL]"
    assert output.results[0].snippet == "contact [EMAIL]"
    assert output.results[0].search_result_id == "00000000000000000000000000000001"
    assert "secret-value" not in output.results[0].url


@pytest.mark.parametrize("result", [({"title": "x"},), (object(),), ((), (),)])
async def test_provider_malformedを固定errorへ変換する(result: Any) -> None:
    with pytest.raises(ToolDomainError) as raised:
        await _handler(Provider(result)).execute(
            _context(), WebSearchInput(query="query", limit=1)
        )
    assert raised.value.code == "WEB_SEARCH_FAILED"
    assert raised.value.retryable is True


async def test_provider_failureを固定retryable_errorへ変換する() -> None:
    with pytest.raises(ToolDomainError) as raised:
        await _handler(Provider(WebSearchProviderError())).execute(
            _context(), WebSearchInput(query="query", limit=1)
        )
    assert raised.value.code == "WEB_SEARCH_FAILED"
    assert raised.value.retryable is True


def test_web_fetchはopaque_idだけを受け取りdirect_urlを拒否する() -> None:
    WebFetchInput.model_validate({"search_result_id": "0" * 32})
    with pytest.raises(ValidationError):
        WebFetchInput.model_validate(
            {"search_result_id": "0" * 32, "url": "https://example.com"}
        )
    with pytest.raises(ValidationError):
        WebFetchInput.model_validate({"search_result_id": "not-an-id"})
