from typing import Any, cast

import httpx
import pytest
from pydantic import SecretStr

from agent_runtime.firewall import FakeAgentFirewall, OrcaRouterAgentFirewall
from agent_runtime.real_runner import RealAgentRunner
from agent_runtime.web_tools import WebToolDependencies
from api.container import build_default_context
from clients.embedding import OrcaRouterEmbeddingClient
from clients.errors import (
    EmbeddingError,
    XApiConfigurationError,
    XApiOutcomeUnknownError,
    XApiProviderError,
    XApiRejectedError,
    XApiRetryableProviderError,
)
from clients.fakes import FakeEmbeddingClient, FakeGa4Client, FakeXApiClient
from clients.ga4 import HttpGa4Client
from clients.web_fetch import FakeWebFetcher, SafeWebFetcher
from clients.web_search import FakeWebSearchProvider, HttpWebSearchProvider, WebSearchProviderError
from clients.x_api import HttpXApiClient
from core.config import Settings
from domain.enums import AgentType
from services.context import ServiceContext

DIMENSIONS = 4
SECRET = "unit-test-secret-unit-test-secret-0123456789"


def _embedding_client(
    handler: httpx.MockTransport, sleeps: list[float] | None = None, **kwargs: str
) -> OrcaRouterEmbeddingClient:
    async def sleep(seconds: float) -> None:
        if sleeps is not None:
            sleeps.append(seconds)

    return OrcaRouterEmbeddingClient(
        base_url=kwargs.get("base_url", "https://router.example.com/v1"),
        api_key=kwargs.get("api_key", "key"),
        model="m",
        dimensions=DIMENSIONS,
        timeout_seconds=1,
        transport=handler,
        sleep=sleep,
    )


def _ok_embedding(vector: list[float]) -> httpx.Response:
    return httpx.Response(200, json={"data": [{"embedding": vector}]})


async def test_Embedding成功_ベクトルを返しリクエストにモデルと次元数を含める() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _ok_embedding([0.1, 0.2, 0.3, 0.4])

    result = await _embedding_client(httpx.MockTransport(handler)).embed("text")

    assert result == [0.1, 0.2, 0.3, 0.4]
    assert seen[0].url == "https://router.example.com/v1/embeddings"
    assert seen[0].headers["authorization"] == "Bearer key"
    assert b'"dimensions":4' in seen[0].content.replace(b" ", b"")


async def test_Embedding再試行_429と5xxは最大3回まで再試行し成功すれば返す() -> None:
    responses = [httpx.Response(429), httpx.Response(503), _ok_embedding([1, 2, 3, 4])]
    sleeps: list[float] = []

    result = await _embedding_client(
        httpx.MockTransport(lambda _request: responses.pop(0)), sleeps
    ).embed("text")

    assert result == [1.0, 2.0, 3.0, 4.0]
    assert len(sleeps) == 2


async def test_Embedding再試行の上限_3回続けて失敗したときEmbeddingError() -> None:
    calls: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(500)

    with pytest.raises(EmbeddingError):
        await _embedding_client(httpx.MockTransport(handler)).embed("text")

    assert len(calls) == 3


async def test_Embedding再試行しない_4xxのときは1回でEmbeddingError() -> None:
    calls: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(401)

    with pytest.raises(EmbeddingError):
        await _embedding_client(httpx.MockTransport(handler)).embed("text")

    assert len(calls) == 1


async def test_Embedding次元数不一致_設定と異なる長さのときEmbeddingError() -> None:
    client = _embedding_client(httpx.MockTransport(lambda _r: _ok_embedding([1.0, 2.0])))

    with pytest.raises(EmbeddingError, match="次元数"):
        await client.embed("text")


async def test_Embedding応答不正_dataがないときEmbeddingError() -> None:
    client = _embedding_client(httpx.MockTransport(lambda _r: httpx.Response(200, json={})))

    with pytest.raises(EmbeddingError):
        await client.embed("text")


async def test_Embedding設定なし_base_urlが空のときEmbeddingErrorで通信しない() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("通信してはいけない")

    with pytest.raises(EmbeddingError):
        await _embedding_client(httpx.MockTransport(handler), base_url="").embed("text")


async def test_Embeddingのエラー文言_通信エラーの詳細と認証情報を含めない() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom key=secret", request=request)

    with pytest.raises(EmbeddingError) as info:
        await _embedding_client(httpx.MockTransport(handler)).embed("text")

    assert "secret" not in str(info.value)


def _x_client(
    handler: httpx.MockTransport,
    *,
    api_key: str = "api-key",
    api_key_secret: str = "api-secret",
    access_token: str = "access-token",
    access_token_secret: str = "access-secret",
) -> HttpXApiClient:
    return HttpXApiClient(
        base_url="https://api.x.example",
        api_key=api_key,
        api_key_secret=api_key_secret,
        access_token=access_token,
        access_token_secret=access_token_secret,
        timeout_seconds=1,
        transport=handler,
        oauth_nonce="fixed-nonce",
        oauth_timestamp="1700000000",
    )


async def test_X投稿成功_201のときx_post_idを返しOAuth1署名で認証する() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"data": {"id": "123", "text": "t"}})

    result = await _x_client(httpx.MockTransport(handler)).post("本文")

    assert result.x_post_id == "123"
    assert seen[0].url == "https://api.x.example/2/tweets"
    assert seen[0].headers["authorization"] == (
        'OAuth oauth_nonce="fixed-nonce", oauth_timestamp="1700000000", '
        'oauth_version="1.0", oauth_signature_method="HMAC-SHA1", '
        'oauth_consumer_key="api-key", oauth_token="access-token", '
        'oauth_signature="mq1SEiOvuTikTTcv%2BsggpW5XMt4%3D"'
    )


@pytest.mark.parametrize("status", [400, 401, 403, 429])
async def test_X投稿拒否_4xxのとき拒否として扱い再試行しない(status: int) -> None:
    calls: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(status, json={"title": "Rejected", "detail": "not created"})

    with pytest.raises(XApiRejectedError) as info:
        await _x_client(httpx.MockTransport(handler)).post("本文")

    assert info.value.status_code == status
    assert len(calls) == 1


@pytest.mark.parametrize("response", [httpx.Response(400), httpx.Response(408)])
async def test_X投稿結果不明_構造化されていない4xxと408は結果不明として扱う(
    response: httpx.Response,
) -> None:
    calls: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return response

    with pytest.raises(XApiOutcomeUnknownError):
        await _x_client(httpx.MockTransport(handler)).post("本文")

    assert len(calls) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"title": "", "detail": ""},
        {"errors": []},
        {"errors": [{}]},
        {"errors": ["not structured"]},
    ],
)
async def test_X投稿結果不明_4xxのError構造が不完全なとき結果不明(body: object) -> None:
    response = httpx.Response(400, json=body)

    with pytest.raises(XApiOutcomeUnknownError):
        await _x_client(httpx.MockTransport(lambda _request: response)).post("本文")


@pytest.mark.parametrize("status", [500, 502, 503])
async def test_X投稿結果不明_5xxのとき結果不明として扱い再試行しない(status: int) -> None:
    calls: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(status)

    with pytest.raises(XApiOutcomeUnknownError):
        await _x_client(httpx.MockTransport(handler)).post("本文")

    assert len(calls) == 1


async def test_X投稿結果不明_タイムアウトと不正な応答のとき結果不明() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(XApiOutcomeUnknownError):
        await _x_client(httpx.MockTransport(timeout)).post("本文")
    with pytest.raises(XApiOutcomeUnknownError):
        await _x_client(httpx.MockTransport(lambda _r: httpx.Response(201, json={}))).post("本文")


@pytest.mark.parametrize(
    "missing",
    ["api_key", "api_key_secret", "access_token", "access_token_secret"],
)
async def test_X投稿設定不正_credentialが不足するとき送信しない(missing: str) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("通信してはいけない")

    credentials = {
        "api_key": "api-key",
        "api_key_secret": "api-secret",
        "access_token": "access-token",
        "access_token_secret": "access-secret",
    }
    credentials[missing] = ""

    with pytest.raises(XApiConfigurationError):
        await _x_client(httpx.MockTransport(handler), **credentials).post("本文")


@pytest.mark.parametrize("count", [0, 42])
async def test_XMetrics取得_impression_countが0以上の整数なら返す(count: int) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": {"public_metrics": {"impression_count": count}}})

    result = await _x_client(httpx.MockTransport(handler)).get_impression_count("123")

    assert result == count
    assert seen[0].url == "https://api.x.example/2/tweets/123?tweet.fields=public_metrics"
    assert 'oauth_signature="fDfunenbcpLJMxMlXguxijnhWzg%3D"' in seen[0].headers["authorization"]


@pytest.mark.parametrize("count", [-1, True, "1", 1.5, None])
async def test_XMetrics応答不正_impression_countが非負整数でないときProviderError(
    count: object,
) -> None:
    response = httpx.Response(200, json={"data": {"public_metrics": {"impression_count": count}}})

    with pytest.raises(XApiRetryableProviderError):
        await _x_client(httpx.MockTransport(lambda _request: response)).get_impression_count("123")


@pytest.mark.parametrize("status", [408, 429, 500, 503])
async def test_XMetrics一時失敗_408と429と5xxのときRetryableProviderError(status: int) -> None:
    response = httpx.Response(status, json={"detail": "provider-secret-body"})

    with pytest.raises(XApiRetryableProviderError) as info:
        await _x_client(httpx.MockTransport(lambda _request: response)).get_impression_count("123")

    assert "provider-secret-body" not in str(info.value)


async def test_XMetrics認証失敗_401のときCredentialとProviderBodyを例外へ含めない() -> None:
    response = httpx.Response(401, json={"detail": "provider-secret-body"})

    with pytest.raises(XApiConfigurationError) as info:
        await _x_client(httpx.MockTransport(lambda _request: response)).get_impression_count("123")

    error = str(info.value)
    assert "provider-secret-body" not in error
    assert "api-secret" not in error
    assert "access-secret" not in error


async def test_XMetrics取得失敗_404のとき再試行対象外のProviderError() -> None:
    response = httpx.Response(404, json={"detail": "not found"})

    with pytest.raises(XApiProviderError) as info:
        await _x_client(httpx.MockTransport(lambda _request: response)).get_impression_count("123")

    assert not isinstance(info.value, XApiRetryableProviderError)
    assert "not found" not in str(info.value)


async def test_XMetrics通信失敗_timeoutのときRetryableProviderError() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("provider-secret-body", request=request)

    with pytest.raises(XApiRetryableProviderError) as info:
        await _x_client(httpx.MockTransport(timeout)).get_impression_count("123")

    assert "provider-secret-body" not in str(info.value)


async def test_Web検索Providerは認証情報をheaderだけに付け型付き結果を返す() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "results": [{"title": "Example", "url": "https://example.com", "snippet": "text"}]
            },
        )

    provider = HttpWebSearchProvider(
        base_url="https://search.example.com",
        api_key="provider-secret",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )
    rows = await provider.search("masked query", 1)

    assert rows[0].url == "https://example.com"
    assert seen[0].url == "https://search.example.com/search"
    assert seen[0].headers["authorization"] == "Bearer provider-secret"
    assert seen[0].read() == b'{"query":"masked query","limit":1}'


async def test_Web検索Providerは不正応答の本文を例外へ含めない() -> None:
    provider = HttpWebSearchProvider(
        base_url="https://search.example.com",
        api_key="provider-secret",
        timeout_seconds=1,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(500, text="provider-secret-body")
        ),
    )
    with pytest.raises(WebSearchProviderError) as info:
        await provider.search("query", 1)
    assert "provider-secret" not in str(info.value)


def _web_dependencies(context: ServiceContext, tool_name: str) -> WebToolDependencies:
    definition = context.tool_registry.resolve(AgentType.PARENT, tool_name)
    assert definition is not None
    return cast(WebToolDependencies, cast(Any, definition.handler)._deps)


def test_Client_Mode_fakeとrealで実行Clientを切り替える() -> None:
    fake = build_default_context(Settings(auth_cookie_secret=SecretStr(SECRET)))
    real = build_default_context(
        Settings(
            auth_cookie_secret=SecretStr(SECRET),
            embedding_client_mode="real",
            x_api_client_mode="real",
            ga4_client_mode="real",
            web_search_client_mode="real",
            web_fetch_client_mode="real",
            agent_client_mode="real",
            agent_firewall_mode="real",
            orcarouter_base_url="https://router.example.com/v1",
            orcarouter_api_key=SecretStr("router-key"),
            orcarouter_firewall_api_key=SecretStr("firewall-key"),
            agent_model="provider/model",
            x_api_key=SecretStr("x-key"),
            x_api_key_secret=SecretStr("x-key-secret"),
            x_access_token=SecretStr("x-token"),
            x_access_token_secret=SecretStr("x-token-secret"),
            ga4_property_id="123456",
            ga4_service_account_json=SecretStr('{"type":"service_account"}'),
            web_search_base_url="https://search.example.com",
            web_search_api_key=SecretStr("search-secret"),
        )
    )

    assert isinstance(fake.embedding, FakeEmbeddingClient)
    assert isinstance(fake.x_api, FakeXApiClient)
    assert isinstance(fake.ga4, FakeGa4Client)
    assert isinstance(_web_dependencies(fake, "web_search").search_provider, FakeWebSearchProvider)
    assert isinstance(_web_dependencies(fake, "web_fetch").fetcher, FakeWebFetcher)
    assert isinstance(real.embedding, OrcaRouterEmbeddingClient)
    assert isinstance(real.x_api, HttpXApiClient)
    assert isinstance(real.ga4, HttpGa4Client)
    assert isinstance(_web_dependencies(real, "web_search").search_provider, HttpWebSearchProvider)
    assert isinstance(_web_dependencies(real, "web_fetch").fetcher, SafeWebFetcher)
    assert isinstance(real.agent_firewall, OrcaRouterAgentFirewall)
    assert isinstance(real.agent_runner, RealAgentRunner)


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("embedding_client_mode", OrcaRouterEmbeddingClient),
        ("x_api_client_mode", HttpXApiClient),
        ("ga4_client_mode", HttpGa4Client),
        ("web_search_client_mode", HttpWebSearchProvider),
        ("web_fetch_client_mode", SafeWebFetcher),
    ],
)
def test_業務Clientは1つだけrealに切り替えられる(mode: str, expected: type[object]) -> None:
    settings = {
        "auth_cookie_secret": SecretStr(SECRET),
        "orcarouter_base_url": "https://router.example.com/v1",
        "orcarouter_api_key": SecretStr("router-key"),
        "x_api_key": SecretStr("x-key"),
        "x_api_key_secret": SecretStr("x-key-secret"),
        "x_access_token": SecretStr("x-token"),
        "x_access_token_secret": SecretStr("x-token-secret"),
        "ga4_property_id": "123456",
        "ga4_service_account_json": SecretStr('{"type":"service_account"}'),
        "web_search_base_url": "https://search.example.com",
        "web_search_api_key": SecretStr("search-secret"),
        mode: "real",
    }
    context = build_default_context(Settings.model_validate(settings))

    selected = {
        "embedding_client_mode": context.embedding,
        "x_api_client_mode": context.x_api,
        "ga4_client_mode": context.ga4,
        "web_search_client_mode": _web_dependencies(context, "web_search").search_provider,
        "web_fetch_client_mode": _web_dependencies(context, "web_fetch").fetcher,
    }[mode]
    assert isinstance(selected, expected)
    if mode != "embedding_client_mode":
        assert isinstance(context.embedding, FakeEmbeddingClient)
    if mode != "x_api_client_mode":
        assert isinstance(context.x_api, FakeXApiClient)
    if mode != "ga4_client_mode":
        assert isinstance(context.ga4, FakeGa4Client)
    if mode != "web_search_client_mode":
        assert isinstance(
            _web_dependencies(context, "web_search").search_provider, FakeWebSearchProvider
        )
    if mode != "web_fetch_client_mode":
        assert isinstance(_web_dependencies(context, "web_fetch").fetcher, FakeWebFetcher)


def test_Agent_Modeだけrealにして業務ClientはFakeを維持する() -> None:
    context = build_default_context(
        Settings(
            auth_cookie_secret=SecretStr(SECRET),
            agent_client_mode="real",
            orcarouter_base_url="https://router.example.com/v1",
            orcarouter_api_key=SecretStr("router-key"),
            agent_model="provider/model",
        )
    )

    assert isinstance(context.embedding, FakeEmbeddingClient)
    assert isinstance(context.x_api, FakeXApiClient)
    assert isinstance(context.ga4, FakeGa4Client)
    assert isinstance(context.agent_firewall, FakeAgentFirewall)
    assert isinstance(context.agent_runner, RealAgentRunner)
