"""OAuth 1.0a User Contextで呼び出すX API Client。"""

from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.parse import quote

import httpx
from oauthlib.oauth1 import Client as OAuth1Client

from clients.errors import (
    XApiConfigurationError,
    XApiOutcomeUnknownError,
    XApiProviderError,
    XApiRejectedError,
    XApiRetryableProviderError,
)


@dataclass(frozen=True)
class XPostResult:
    """X APIが返した投稿結果。"""

    x_post_id: str


class XApiClient(Protocol):
    """Xへの投稿とMetrics取得を行う。"""

    async def post(self, text: str) -> XPostResult:
        """投稿する。

        Raises:
            XApiRejectedError: Xが失敗を確定して返した（投稿されていない）。
            XApiOutcomeUnknownError: 結果を確定できない（投稿されている可能性がある）。
        """
        ...

    async def get_impression_count(self, x_post_id: str) -> int:
        """投稿のimpression_countを取得する。"""
        ...


class HttpXApiClient:
    """X APIを呼ぶ薄いクライアント。

    副作用のある呼び出しのため、自動で再試行しない（BE_STD 8.3）。
    構造化された4xxは投稿の失敗が確定、Timeout・通信エラー・不正な応答は結果不明とする。
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        api_key_secret: str,
        access_token: str,
        access_token_secret: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
        oauth_nonce: str | None = None,
        oauth_timestamp: str | None = None,
    ) -> None:
        """クライアントを作る。`transport` はテストで差し替える。"""
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._api_key_secret = api_key_secret
        self._access_token = access_token
        self._access_token_secret = access_token_secret
        self._timeout = timeout_seconds
        self._transport = transport
        self._oauth_nonce = oauth_nonce
        self._oauth_timestamp = oauth_timestamp

    async def post(self, text: str) -> XPostResult:
        """投稿する。"""
        self._require_credentials()
        url = f"{self._base_url}/2/tweets"
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=self._timeout
            ) as client:
                response = await client.post(
                    url,
                    headers=self._authorization_header("POST", url),
                    json={"text": text},
                )
        except (httpx.TimeoutException, httpx.TransportError):
            raise XApiOutcomeUnknownError("X APIの結果を確定できませんでした") from None
        if 400 <= response.status_code < 500:
            is_unambiguous = response.status_code != httpx.codes.REQUEST_TIMEOUT
            if is_unambiguous and _is_structured_error(response):
                raise XApiRejectedError(response.status_code)
            raise XApiOutcomeUnknownError("X APIのエラー応答を解釈できませんでした")
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

    async def get_impression_count(self, x_post_id: str) -> int:
        """投稿の公開Metricsからimpression_countを取得する。"""
        self._require_credentials()
        encoded_id = quote(x_post_id, safe="")
        url = f"{self._base_url}/2/tweets/{encoded_id}?tweet.fields=public_metrics"
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=self._timeout
            ) as client:
                response = await client.get(
                    url,
                    headers=self._authorization_header("GET", url),
                )
        except (httpx.TimeoutException, httpx.TransportError):
            raise XApiRetryableProviderError("X APIからMetricsを取得できませんでした") from None
        if response.status_code in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
            raise XApiConfigurationError("X APIのCredentialが拒否されました")
        if (
            response.status_code
            in (
                httpx.codes.REQUEST_TIMEOUT,
                httpx.codes.TOO_MANY_REQUESTS,
            )
            or response.status_code >= 500
        ):
            raise XApiRetryableProviderError("X APIからMetricsを取得できませんでした")
        if response.status_code != httpx.codes.OK:
            raise XApiProviderError("X APIからMetricsを取得できませんでした")
        try:
            impression_count = response.json()["data"]["public_metrics"]["impression_count"]
        except (ValueError, KeyError, TypeError):
            raise XApiRetryableProviderError("X APIのMetrics応答を解釈できませんでした") from None
        if type(impression_count) is not int or impression_count < 0:
            raise XApiRetryableProviderError("X APIのMetrics応答を解釈できませんでした")
        return impression_count

    def _require_credentials(self) -> None:
        """OAuth 1.0aに必要な4 Credentialが揃っていることを確認する。"""
        if not all(
            value.strip()
            for value in (
                self._api_key,
                self._api_key_secret,
                self._access_token,
                self._access_token_secret,
            )
        ):
            raise XApiConfigurationError("X APIのCredentialが設定されていません")

    def _authorization_header(self, method: Literal["GET", "POST"], url: str) -> dict[str, str]:
        """Request URLを含めてOAuth 1.0a署名し、Authorization Headerを返す。"""
        try:
            oauth = OAuth1Client(
                self._api_key,
                client_secret=self._api_key_secret,
                resource_owner_key=self._access_token,
                resource_owner_secret=self._access_token_secret,
                nonce=self._oauth_nonce,
                timestamp=self._oauth_timestamp,
            )
            _, headers, _ = oauth.sign(url, http_method=method)
        except (TypeError, ValueError):
            raise XApiConfigurationError("X APIのOAuth Headerを生成できませんでした") from None
        authorization = headers.get("Authorization")
        if not isinstance(authorization, str):
            raise XApiConfigurationError("X APIのOAuth Headerを生成できませんでした")
        return {"Authorization": authorization}


def _is_structured_error(response: httpx.Response) -> bool:
    """Xが投稿未作成を明示したと判断できる構造化Errorか。"""
    try:
        body = response.json()
    except ValueError:
        return False
    if not isinstance(body, dict):
        return False
    if _has_text(body, "title", "detail"):
        return True
    errors = body.get("errors")
    return isinstance(errors, list) and any(
        isinstance(error, dict) and _has_text(error, "title", "detail", "message", "reason")
        for error in errors
    )


def _has_text(value: dict[object, object], *keys: str) -> bool:
    """指定されたFieldのいずれかに空でない文字列があるか。"""
    return any(isinstance(value.get(key), str) and bool(str(value[key]).strip()) for key in keys)
