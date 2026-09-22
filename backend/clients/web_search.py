"""型付きWeb検索Provider client。"""

from typing import Protocol

import httpx
from pydantic import Field, ValidationError

from agent_runtime.tools import StrictToolModel


class ProviderSearchResult(StrictToolModel):
    """Providerから受け入れる検索結果。"""

    title: str = Field(min_length=1, max_length=1_000)
    url: str = Field(min_length=1, max_length=8_000)
    snippet: str = Field(max_length=4_000)


class WebSearchProviderError(Exception):
    """検索Providerの通信・形式エラー。詳細を外へ出さない。"""


class WebSearchProvider(Protocol):
    """Web検索Provider境界。"""

    async def search(self, query: str, limit: int) -> tuple[ProviderSearchResult, ...]:
        """検索結果を返す。"""
        ...


class HttpWebSearchProvider:
    """JSON APIを呼ぶ検索Provider。"""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Provider接続設定を保持する。"""
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._transport = transport

    async def search(self, query: str, limit: int) -> tuple[ProviderSearchResult, ...]:
        """Providerを呼び、厳密に検証した結果だけを返す。"""
        if not self._base_url or not self._api_key:
            raise WebSearchProviderError
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, trust_env=False, transport=self._transport
            ) as client:
                response = await client.post(
                    f"{self._base_url}/search",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={"query": query, "limit": limit},
                )
            response.raise_for_status()
            payload = response.json()
            values = payload["results"]
            if not isinstance(values, list) or len(values) > limit:
                raise ValueError
            return tuple(ProviderSearchResult.model_validate(value) for value in values)
        except (httpx.HTTPError, KeyError, TypeError, ValueError, ValidationError) as error:
            raise WebSearchProviderError from error


class FakeWebSearchProvider:
    """fake modeで外部通信しない検索Provider。"""

    async def search(self, query: str, limit: int) -> tuple[ProviderSearchResult, ...]:
        """空の検索結果を返す。"""
        del query, limit
        return ()
