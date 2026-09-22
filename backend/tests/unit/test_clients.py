import httpx
import pytest
from pydantic import SecretStr

from api.container import build_default_context
from clients.embedding import OrcaRouterEmbeddingClient
from clients.errors import EmbeddingError, XApiOutcomeUnknownError, XApiRejectedError
from clients.fakes import FakeEmbeddingClient, FakeXApiClient
from clients.x_api import HttpXApiClient
from core.config import Settings

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


def _x_client(handler: httpx.MockTransport, token: str = "token") -> HttpXApiClient:
    return HttpXApiClient(
        base_url="https://api.x.example", access_token=token, timeout_seconds=1, transport=handler
    )


async def test_X投稿成功_201のときx_post_idを返しBearerで認証する() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"data": {"id": "123", "text": "t"}})

    result = await _x_client(httpx.MockTransport(handler)).post("本文")

    assert result.x_post_id == "123"
    assert seen[0].url == "https://api.x.example/2/tweets"
    assert seen[0].headers["authorization"] == "Bearer token"


@pytest.mark.parametrize("status", [400, 401, 403, 429])
async def test_X投稿拒否_4xxのとき拒否として扱い再試行しない(status: int) -> None:
    calls: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(status, json={"title": "Rejected", "detail": "not created"})

    with pytest.raises(XApiRejectedError) as info:
        await _x_client(httpx.MockTransport(handler)).post("本文")

    assert info.value.retryable is (status == 429)
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


async def test_X投稿_アクセストークンがないとき送信せず拒否として扱う() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("通信してはいけない")

    with pytest.raises(XApiRejectedError):
        await _x_client(httpx.MockTransport(handler), token="").post("本文")


def test_Client_Mode_fakeとrealで実行Clientを切り替える() -> None:
    fake = build_default_context(Settings(auth_cookie_secret=SecretStr(SECRET)))
    real = build_default_context(
        Settings(
            auth_cookie_secret=SecretStr(SECRET),
            external_client_mode="real",
            orcarouter_base_url="https://router.example.com/v1",
            orcarouter_api_key=SecretStr("router-key"),
            x_api_key=SecretStr("x-key"),
            x_api_key_secret=SecretStr("x-key-secret"),
            x_access_token=SecretStr("x-token"),
            x_access_token_secret=SecretStr("x-token-secret"),
            ga4_property_id="123456",
            ga4_service_account_json=SecretStr('{"type":"service_account"}'),
        )
    )

    assert isinstance(fake.embedding, FakeEmbeddingClient)
    assert isinstance(fake.x_api, FakeXApiClient)
    assert isinstance(real.embedding, OrcaRouterEmbeddingClient)
    assert isinstance(real.x_api, HttpXApiClient)
