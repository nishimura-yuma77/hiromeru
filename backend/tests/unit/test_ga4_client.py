import json
from datetime import UTC, datetime

import httpx
import pytest
from pydantic import SecretStr

from api.container import build_default_context
from clients.errors import Ga4ConfigurationError, Ga4ProviderError, Ga4RetryableProviderError
from clients.fakes import FakeGa4Client
from clients.ga4 import (
    Ga4ReportQuery,
    GoogleServiceAccountTokenProvider,
    HttpGa4Client,
    report_date_range,
)
from core.config import Settings

SECRET = "unit-test-secret-unit-test-secret-0123456789"


class _TokenProvider:
    async def get_access_token(self) -> str:
        return "access-token"


def _query(
    *,
    published_at: datetime = datetime(2026, 1, 1, 15, 0, tzinfo=UTC),
    scheduled_at: datetime = datetime(2026, 1, 8, 15, 0, tzinfo=UTC),
) -> Ga4ReportQuery:
    return Ga4ReportQuery(
        published_at=published_at,
        scheduled_at=scheduled_at,
        utm_source="Stored-Source",
        utm_medium="Stored-Medium",
        utm_campaign="Stored-Campaign",
        utm_content="Stored-Content",
    )


def _client(handler: httpx.MockTransport, *, property_id: str = "123") -> HttpGa4Client:
    return HttpGa4Client(
        property_id=property_id,
        token_provider=_TokenProvider(),
        timeout_seconds=1,
        base_url="https://analytics.example/v1beta",
        transport=handler,
    )


@pytest.mark.parametrize(
    ("published_at", "scheduled_at", "expected"),
    [
        (
            datetime(2026, 1, 1, 14, 59, 59, tzinfo=UTC),
            datetime(2026, 1, 8, 14, 59, 59, tzinfo=UTC),
            ("2026-01-01", "2026-01-07"),
        ),
        (
            datetime(2026, 1, 1, 15, 0, tzinfo=UTC),
            datetime(2026, 1, 8, 15, 0, tzinfo=UTC),
            ("2026-01-02", "2026-01-08"),
        ),
    ],
)
def test_GA4期間は公開日時と計測予定日時をJST暦日へ変換する(
    published_at: datetime, scheduled_at: datetime, expected: tuple[str, str]
) -> None:
    start, end = report_date_range(published_at, scheduled_at)

    assert (start.isoformat(), end.isoformat()) == expected


async def test_GA4はactiveUsersと保存済みUTMの4条件AND完全一致を送る() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={"rowCount": 1, "rows": [{"metricValues": [{"value": "7"}]}]},
        )

    result = await _client(httpx.MockTransport(handler)).get_active_users(_query())

    assert result == 7
    assert seen[0].url == "https://analytics.example/v1beta/properties/123:runReport"
    assert seen[0].headers["authorization"] == "Bearer access-token"
    body = json.loads(seen[0].content)
    assert body["dateRanges"] == [{"startDate": "2026-01-02", "endDate": "2026-01-08"}]
    assert body["metrics"] == [{"name": "activeUsers"}]
    assert body["dimensionFilter"]["andGroup"]["expressions"] == [
        {
            "filter": {
                "fieldName": field,
                "stringFilter": {
                    "matchType": "EXACT",
                    "value": value,
                    "caseSensitive": True,
                },
            }
        }
        for field, value in (
            ("sessionManualSource", "Stored-Source"),
            ("sessionManualMedium", "Stored-Medium"),
            ("sessionManualCampaignName", "Stored-Campaign"),
            ("sessionManualAdContent", "Stored-Content"),
        )
    ]


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"rowCount": 0}, 0),
        ({"rowCount": 0, "rows": []}, 0),
        ({"rowCount": 1, "rows": [{"metricValues": [{"value": "0"}]}]}, 0),
        ({"rowCount": 1, "rows": [{"metricValues": [{"value": "123"}]}]}, 123),
    ],
)
async def test_GA4の0行と非負整数を実測値として返す(
    body: dict[str, object], expected: int
) -> None:
    client = _client(httpx.MockTransport(lambda _request: httpx.Response(200, json=body)))

    assert await client.get_active_users(_query()) == expected


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"rowCount": 1},
        {"rowCount": 1, "rows": []},
        {"rowCount": 1, "rows": [{"metricValues": []}]},
        {"rowCount": 1, "rows": [{"metricValues": [{"value": -1}]}]},
        {"rowCount": 1, "rows": [{"metricValues": [{"value": "-1"}]}]},
        {"rowCount": 1, "rows": [{"metricValues": [{"value": "1.5"}]}]},
        {"rowCount": 1, "rows": [{"metricValues": [{"value": True}]}]},
    ],
)
async def test_GA4の型不正または負数は再試行可能Error(body: dict[str, object]) -> None:
    client = _client(httpx.MockTransport(lambda _request: httpx.Response(200, json=body)))

    with pytest.raises(Ga4RetryableProviderError):
        await client.get_active_users(_query())


@pytest.mark.parametrize("status", [401, 403])
async def test_GA4の認証権限Errorは再試行不能(status: int) -> None:
    client = _client(httpx.MockTransport(lambda _request: httpx.Response(status)))

    with pytest.raises(Ga4ConfigurationError):
        await client.get_active_users(_query())


@pytest.mark.parametrize("status", [408, 429, 500, 503])
async def test_GA4の一時ProviderErrorは再試行可能(status: int) -> None:
    client = _client(httpx.MockTransport(lambda _request: httpx.Response(status)))

    with pytest.raises(Ga4RetryableProviderError):
        await client.get_active_users(_query())


async def test_GA4の恒久的4xxは再試行不能でProvider本文を含めない() -> None:
    client = _client(
        httpx.MockTransport(
            lambda _request: httpx.Response(400, text="provider-secret-response-body")
        )
    )

    with pytest.raises(Ga4ProviderError) as info:
        await client.get_active_users(_query())

    assert "provider-secret-response-body" not in str(info.value)
    assert not isinstance(info.value, Ga4RetryableProviderError)


async def test_GA4のTimeoutは詳細を含まない再試行可能Error() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("credential=secret", request=request)

    with pytest.raises(Ga4RetryableProviderError) as info:
        await _client(httpx.MockTransport(timeout)).get_active_users(_query())

    assert "secret" not in str(info.value)


async def test_GA4のCredential不正は通信せず安全な設定Error() -> None:
    credential = '{"private_key":"super-secret"}'
    provider = GoogleServiceAccountTokenProvider(credential)

    with pytest.raises(Ga4ConfigurationError) as info:
        await provider.get_access_token()

    assert "super-secret" not in str(info.value)


async def test_GA4_FakeはLive_Requestなしで0を返す() -> None:
    assert await FakeGa4Client().get_active_users(_query()) == 0
    context = build_default_context(
        Settings(
            auth_cookie_secret=SecretStr(SECRET),
            cookie_secure=False,
            external_client_mode="fake",
        )
    )
    assert isinstance(context.ga4, FakeGa4Client)
