"""Embedding生成のクライアント（OrcaRouter経由。BE_STD 13章、17.3）。"""

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import Protocol

import httpx

from clients.errors import EmbeddingError

_MAX_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 0.5
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class EmbeddingClient(Protocol):
    """テキストからEmbeddingを生成する。"""

    async def embed(self, text: str) -> list[float]:
        """Embeddingを返す。

        Raises:
            EmbeddingError: 生成できなかった場合。
        """
        ...


class OrcaRouterEmbeddingClient:
    """OrcaRouter（OpenAI互換の `/embeddings`）を呼ぶ薄いクライアント。

    一時的なエラー（429、5xx、タイムアウト）だけを、最大3回まで指数バックオフで再試行する。
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        dimensions: int,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """クライアントを作る。`transport` はテストで差し替える。"""
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._dimensions = dimensions
        self._timeout = timeout_seconds
        self._transport = transport
        self._sleep = sleep

    async def embed(self, text: str) -> list[float]:
        """Embeddingを返す。"""
        if not self._base_url or not self._api_key:
            raise EmbeddingError("Embeddingの接続設定がありません")
        last_error: EmbeddingError | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                return await self._request(text)
            except _RetryableError as error:
                last_error = EmbeddingError(str(error))
                if attempt + 1 < _MAX_ATTEMPTS:
                    delay = _BACKOFF_BASE_SECONDS * (2**attempt) * (0.5 + random.random())  # noqa: S311
                    await self._sleep(delay)
        raise last_error or EmbeddingError("Embeddingを生成できません")

    async def _request(self, text: str) -> list[float]:
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=self._timeout
            ) as client:
                response = await client.post(
                    f"{self._base_url}/embeddings",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={"model": self._model, "input": text, "dimensions": self._dimensions},
                )
        except (httpx.TimeoutException, httpx.TransportError) as error:
            # 認証情報を含み得る詳細は保持せず、種別だけを伝える。
            raise _RetryableError(
                f"Embedding APIの通信に失敗しました ({type(error).__name__})"
            ) from None
        if response.status_code in _RETRYABLE_STATUS:
            raise _RetryableError(f"Embedding APIが一時的に失敗しました ({response.status_code})")
        if response.status_code != httpx.codes.OK:
            raise EmbeddingError(f"Embedding APIがエラーを返しました ({response.status_code})")
        return self._parse(response)

    def _parse(self, response: httpx.Response) -> list[float]:
        try:
            vector = response.json()["data"][0]["embedding"]
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise EmbeddingError("Embedding APIの応答が不正です") from error
        if (
            not isinstance(vector, list)
            or len(vector) != self._dimensions
            or not all(isinstance(value, int | float) for value in vector)
        ):
            raise EmbeddingError("Embeddingの次元数が設定と一致しません")
        return [float(value) for value in vector]


class _RetryableError(Exception):
    """再試行できる一時的なエラー（内部用）。"""
