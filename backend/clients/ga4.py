"""Service Accountで呼び出すGoogle Analytics Data API Client。"""

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Protocol, cast
from zoneinfo import ZoneInfo

import httpx
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from clients.errors import Ga4ConfigurationError, Ga4ProviderError, Ga4RetryableProviderError

_GA4_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
_TOKYO = ZoneInfo("Asia/Tokyo")
_NON_NEGATIVE_INTEGER = re.compile(r"^(?:0|[1-9][0-9]*)$")


@dataclass(frozen=True)
class Ga4ReportQuery:
    """投稿の初週流入Userを識別する、DB由来の入力。"""

    published_at: datetime
    scheduled_at: datetime
    utm_source: str
    utm_medium: str
    utm_campaign: str
    utm_content: str


class Ga4Client(Protocol):
    """GA4から投稿の初週流入User数を取得する。"""

    async def get_active_users(self, query: Ga4ReportQuery) -> int:
        """保存済みUTMと公開期間に一致するactiveUsersを返す。"""
        ...


class AccessTokenProvider(Protocol):
    """GA4 Request用の短命Access Tokenを供給する。"""

    async def get_access_token(self) -> str:
        """有効なAccess Tokenを返す。"""
        ...


class GoogleServiceAccountTokenProvider:
    """Service Account JSONからAccess Tokenを取得する。"""

    def __init__(self, service_account_json: str) -> None:
        """Credential文字列をMemory内だけで保持する。"""
        self._service_account_json = service_account_json
        self._credentials: service_account.Credentials | None = None
        self._lock = asyncio.Lock()

    def _load_credentials(self) -> service_account.Credentials:
        """最初の利用時にCredentialを解釈する。"""
        if self._credentials is not None:
            return self._credentials
        try:
            info = json.loads(self._service_account_json)
            if not isinstance(info, dict):
                raise ValueError
            credentials = service_account.Credentials.from_service_account_info(
                info, scopes=(_GA4_SCOPE,)
            )
        except (GoogleAuthError, TypeError, ValueError):
            raise Ga4ConfigurationError("GA4のCredentialを解釈できませんでした") from None
        self._credentials = credentials
        return credentials

    async def get_access_token(self) -> str:
        """必要な場合だけCredentialを更新し、Tokenを返す。"""
        async with self._lock:
            credentials = self._load_credentials()
            if not credentials.valid:
                try:
                    await asyncio.to_thread(credentials.refresh, Request())
                except (GoogleAuthError, OSError):
                    raise Ga4ConfigurationError("GA4のCredentialを更新できませんでした") from None
            token = credentials.token
        if not isinstance(token, str) or not token:
            raise Ga4ConfigurationError("GA4のAccess Tokenを取得できませんでした")
        return token


class HttpGa4Client:
    """GA4 Data API v1betaを呼ぶ薄いClient。"""

    def __init__(
        self,
        *,
        property_id: str,
        token_provider: AccessTokenProvider,
        timeout_seconds: float,
        base_url: str = "https://analyticsdata.googleapis.com/v1beta",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """接続設定を保持する。`transport`はテストで差し替える。"""
        self._property_id = property_id
        self._token_provider = token_provider
        self._timeout = timeout_seconds
        self._base_url = base_url.rstrip("/")
        self._transport = transport

    async def get_active_users(self, query: Ga4ReportQuery) -> int:
        """初週のactiveUsersを取得する。Client内では再試行しない。"""
        if not self._property_id.strip() or not self._base_url:
            raise Ga4ConfigurationError("GA4の接続設定がありません")
        token = await self._token_provider.get_access_token()
        url = f"{self._base_url}/properties/{self._property_id}:runReport"
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=self._timeout
            ) as client:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                    json=_report_body(query),
                )
        except (httpx.TimeoutException, httpx.TransportError):
            raise Ga4RetryableProviderError("GA4からMetricsを取得できませんでした") from None
        if response.status_code in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
            raise Ga4ConfigurationError("GA4のCredentialまたは権限が拒否されました")
        if (
            response.status_code
            in (
                httpx.codes.REQUEST_TIMEOUT,
                httpx.codes.TOO_MANY_REQUESTS,
            )
            or response.status_code >= 500
        ):
            raise Ga4RetryableProviderError("GA4からMetricsを取得できませんでした")
        if response.status_code != httpx.codes.OK:
            raise Ga4ProviderError("GA4からMetricsを取得できませんでした")
        return _active_users(response)


def report_date_range(published_at: datetime, scheduled_at: datetime) -> tuple[date, date]:
    """UTC日時をGA4 Propertyと同じJST暦日の範囲へ変換する。"""
    start_date = published_at.astimezone(_TOKYO).date()
    end_date = scheduled_at.astimezone(_TOKYO).date() - timedelta(days=1)
    if end_date < start_date:
        raise Ga4ProviderError("GA4の計測期間が不正です")
    return start_date, end_date


def _report_body(query: Ga4ReportQuery) -> dict[str, Any]:
    start_date, end_date = report_date_range(query.published_at, query.scheduled_at)
    dimensions = (
        ("sessionManualSource", query.utm_source),
        ("sessionManualMedium", query.utm_medium),
        ("sessionManualCampaignName", query.utm_campaign),
        ("sessionManualAdContent", query.utm_content),
    )
    return {
        "dateRanges": [{"startDate": start_date.isoformat(), "endDate": end_date.isoformat()}],
        "metrics": [{"name": "activeUsers"}],
        "dimensionFilter": {
            "andGroup": {
                "expressions": [
                    {
                        "filter": {
                            "fieldName": name,
                            "stringFilter": {
                                "matchType": "EXACT",
                                "value": value,
                                "caseSensitive": True,
                            },
                        }
                    }
                    for name, value in dimensions
                ]
            }
        },
    }


def _active_users(response: httpx.Response) -> int:
    try:
        body = response.json()
    except ValueError:
        raise Ga4RetryableProviderError("GA4のMetrics応答を解釈できませんでした") from None
    if not isinstance(body, dict):
        raise Ga4RetryableProviderError("GA4のMetrics応答を解釈できませんでした")
    rows = body.get("rows")
    row_count = body.get("rowCount")
    if rows in (None, []) and type(row_count) is int and row_count == 0:
        return 0
    try:
        if type(row_count) is not int or row_count != 1:
            raise ValueError
        if not isinstance(rows, list) or len(rows) != 1:
            raise ValueError
        metric_values = rows[0]["metricValues"]
        if not isinstance(metric_values, list) or len(metric_values) != 1:
            raise ValueError
        value = metric_values[0]["value"]
    except (IndexError, KeyError, TypeError, ValueError):
        raise Ga4RetryableProviderError("GA4のMetrics応答を解釈できませんでした") from None
    if not isinstance(value, str) or _NON_NEGATIVE_INTEGER.fullmatch(value) is None:
        raise Ga4RetryableProviderError("GA4のMetrics応答を解釈できませんでした")
    return int(cast(str, value))
