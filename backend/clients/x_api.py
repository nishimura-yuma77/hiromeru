"""X APIのクライアント（POST /2/tweets）。"""

from dataclasses import dataclass
from typing import Protocol

import httpx

from clients.errors import XApiOutcomeUnknownError, XApiRejectedError


@dataclass(frozen=True)
class XPostResult:
    """X APIが返した投稿結果。"""

    x_post_id: str


class XApiClient(Protocol):
    """Xへ投稿する。"""

    async def post(self, text: str) -> XPostResult:
        """投稿する。

        Raises:
            XApiRejectedError: Xが失敗を確定して返した（投稿されていない）。
            XApiOutcomeUnknownError: 結果を確定できない（投稿されている可能性がある）。
        """
        ...


class HttpXApiClient:
    """X APIを呼ぶ薄いクライアント。

    副作用のある呼び出しのため、自動で再試行しない（BE_STD 8.3）。
    4xx は投稿の失敗が確定、5xx・タイムアウト・通信エラー・不正な応答は結果不明として扱う。
    """

    def __init__(
        self,
        *,
        base_url: str,
        access_token: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """クライアントを作る。`transport` はテストで差し替える。"""
        self._base_url = base_url.rstrip("/")
        self._access_token = access_token
        self._timeout = timeout_seconds
        self._transport = transport

    async def post(self, text: str) -> XPostResult:
        """投稿する。"""
        if not self._access_token:
            # 送信前に確定できる失敗のため、投稿されていない。
            raise XApiRejectedError(401)
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=self._timeout
            ) as client:
                response = await client.post(
                    f"{self._base_url}/2/tweets",
                    headers={"Authorization": f"Bearer {self._access_token}"},
                    json={"text": text},
                )
        except (httpx.TimeoutException, httpx.TransportError):
            raise XApiOutcomeUnknownError("X APIの結果を確定できませんでした") from None
        if 400 <= response.status_code < 500:
            raise XApiRejectedError(response.status_code)
        if response.status_code not in (httpx.codes.CREATED, httpx.codes.OK):
            raise XApiOutcomeUnknownError(
                f"X APIが想定外の応答を返しました ({response.status_code})"
            )
        try:
            x_post_id = response.json()["data"]["id"]
        except (ValueError, KeyError, TypeError):
            raise XApiOutcomeUnknownError("X APIの応答を解釈できませんでした") from None
        if not isinstance(x_post_id, str) or not x_post_id:
            raise XApiOutcomeUnknownError("X APIの応答に投稿IDがありません")
        return XPostResult(x_post_id=x_post_id)
