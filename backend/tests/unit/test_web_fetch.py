from collections.abc import AsyncIterator, Mapping

import httpx
import pytest

from clients.web_fetch import (
    ContentTooLargeError,
    FakeWebFetcher,
    HttpxPinnedTransport,
    PinnedResponse,
    ResolvedUrl,
    SafeWebFetcher,
    UnsafeUrlError,
    WebFetchError,
    resolve_url,
)


async def _chunks(*values: bytes) -> AsyncIterator[bytes]:
    for value in values:
        yield value


async def _close() -> None:
    return None


async def test_Fake_Web_Fetchは外部通信せず固定本文を返す() -> None:
    fetcher = FakeWebFetcher()

    target = await fetcher.resolve("https://Example.com/path#fragment")
    final_url, content = await fetcher.fetch(target)

    assert final_url == "https://example.com/path"
    assert content == "Fake web content for external-client isolation."
    with pytest.raises(UnsafeUrlError):
        await fetcher.resolve("http://example.com/path")


class Resolver:
    def __init__(self, answers: dict[str, tuple[str, ...]]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, int]] = []

    async def resolve(self, host: str, port: int) -> tuple[str, ...]:
        self.calls.append((host, port))
        return self.answers[host]


class Transport:
    def __init__(self, responses: list[PinnedResponse]) -> None:
        self.responses = responses
        self.requests: list[tuple[ResolvedUrl, Mapping[str, str]]] = []

    async def request(self, target: ResolvedUrl, headers: Mapping[str, str]) -> PinnedResponse:
        self.requests.append((target, headers))
        return self.responses.pop(0)


class CloseRecorder:
    def __init__(self) -> None:
        self.called = False

    async def __call__(self) -> None:
        self.called = True


def _response(
    status: int = 200,
    *,
    headers: Mapping[str, str] | None = None,
    chunks: tuple[bytes, ...] = (b"ok",),
) -> PinnedResponse:
    return PinnedResponse(
        status,
        {"content-type": "text/plain"} if headers is None else headers,
        _chunks(*chunks),
        _close,
    )


@pytest.mark.parametrize(
    "address",
    [
        "10.0.0.1",
        "127.0.0.1",
        "169.254.169.254",
        "0.0.0.0",  # noqa: S104 - SSRF拒否対象の明示的なtest vector
        "224.0.0.1",
        "192.0.2.1",
        "::1",
        "fe80::1",
        "ff02::1",
        "::",
        "::ffff:10.0.0.1",
    ],
)
async def test_private_reserved_metadataとmapped_ipv6を拒否する(address: str) -> None:
    resolver = Resolver({"example.com": (address,)})
    with pytest.raises(UnsafeUrlError):
        await resolve_url("https://example.com/path", resolver)


async def test_mixed_dns_answerは全体を拒否する() -> None:
    resolver = Resolver({"example.com": ("93.184.216.34", "127.0.0.1")})
    with pytest.raises(UnsafeUrlError):
        await resolve_url("https://example.com", resolver)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://user:pass@example.com",
        "https://example.com:444",
        "https://example.com/\nheader",
        "https://example.com\\@evil.example/",
        "not a url",
    ],
)
async def test_malformed_userinfo_http_controlを拒否する(url: str) -> None:
    with pytest.raises(UnsafeUrlError):
        await resolve_url(url, Resolver({"example.com": ("93.184.216.34",)}))


async def test_dns検査後は固定ipだけをtransportへ渡し再resolveしない() -> None:
    resolver = Resolver({"example.com": ("93.184.216.34",)})
    transport = Transport([_response()])
    fetcher = SafeWebFetcher(resolver=resolver, transport=transport, max_bytes=100, max_redirects=2)
    target = await fetcher.resolve("https://example.com/a")
    resolver.answers["example.com"] = ("127.0.0.1",)

    assert await fetcher.fetch(target) == ("https://example.com/a", "ok")
    assert resolver.calls == [("example.com", 443)]
    assert transport.requests[0][0].ips == ("93.184.216.34",)
    assert set(transport.requests[0][1]) == {"Accept", "Accept-Encoding", "User-Agent"}


async def test_httpx_transportはipへ接続しhostとsniを元hostにする() -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            stream=httpx.ByteStream(b"ok"),
        )

    transport = HttpxPinnedTransport(1, httpx.MockTransport(handler))
    response = await transport.request(
        ResolvedUrl("https://example.com/a", "example.com", 443, ("93.184.216.34",)),
        {
            "Accept": "text/plain",
            "Authorization": "Bearer secret",
            "Cookie": "session=secret",
            "X-Internal-Address": "10.0.0.1",
        },
    )
    assert b"".join([chunk async for chunk in response.chunks]) == b"ok"
    assert captured[0].url.host == "93.184.216.34"
    assert captured[0].headers["host"] == "example.com"
    assert captured[0].headers["accept-encoding"] == "identity"
    assert "authorization" not in captured[0].headers
    assert "cookie" not in captured[0].headers
    assert "x-internal-address" not in captured[0].headers
    assert captured[0].extensions["sni_hostname"] == "example.com"


async def test_safe_redirect_chainは各hostを再検証する() -> None:
    resolver = Resolver({"one.example": ("93.184.216.34",), "two.example": ("1.1.1.1",)})
    transport = Transport(
        [
            _response(302, headers={"location": "https://two.example/final"}),
            _response(chunks=(b"done",)),
        ]
    )
    fetcher = SafeWebFetcher(resolver=resolver, transport=transport, max_bytes=100, max_redirects=2)
    result = await fetcher.fetch(await fetcher.resolve("https://one.example/start"))
    assert result == ("https://two.example/final", "done")
    assert [request[0].host for request in transport.requests] == ["one.example", "two.example"]


@pytest.mark.parametrize(
    "location",
    ["http://example.com/down", "https://127.0.0.1/private"],
)
async def test_unsafe_redirectを通信前に拒否する(location: str) -> None:
    resolver = Resolver({"example.com": ("93.184.216.34",)})
    transport = Transport([_response(302, headers={"location": location})])
    fetcher = SafeWebFetcher(resolver=resolver, transport=transport, max_bytes=100, max_redirects=2)
    with pytest.raises(UnsafeUrlError):
        await fetcher.fetch(await fetcher.resolve("https://example.com/start"))
    assert len(transport.requests) == 1


async def test_redirect_loopと上限を拒否する() -> None:
    resolver = Resolver({"example.com": ("93.184.216.34",)})
    loop = SafeWebFetcher(
        resolver=resolver,
        transport=Transport([_response(302, headers={"location": "/a"})]),
        max_bytes=100,
        max_redirects=2,
    )
    with pytest.raises(UnsafeUrlError):
        await loop.fetch(await loop.resolve("https://example.com/a"))

    maximum = SafeWebFetcher(
        resolver=resolver,
        transport=Transport(
            [
                _response(302, headers={"location": "/b"}),
                _response(302, headers={"location": "/c"}),
            ]
        ),
        max_bytes=100,
        max_redirects=1,
    )
    with pytest.raises(UnsafeUrlError):
        await maximum.fetch(await maximum.resolve("https://example.com/a"))


async def test_content_lengthとchunked実byteの上限を検査する() -> None:
    resolver = Resolver({"example.com": ("93.184.216.34",)})
    target = await resolve_url("https://example.com", resolver)
    declared = SafeWebFetcher(
        resolver=resolver,
        transport=Transport(
            [_response(headers={"content-type": "text/plain", "content-length": "11"})]
        ),
        max_bytes=10,
        max_redirects=0,
    )
    with pytest.raises(ContentTooLargeError):
        await declared.fetch(target)
    streamed = SafeWebFetcher(
        resolver=resolver,
        transport=Transport([_response(chunks=(b"123456", b"78901"))]),
        max_bytes=10,
        max_redirects=0,
    )
    with pytest.raises(ContentTooLargeError):
        await streamed.fetch(target)


async def test_compressed_responseを展開前に拒否する() -> None:
    resolver = Resolver({"example.com": ("93.184.216.34",)})
    fetcher = SafeWebFetcher(
        resolver=resolver,
        transport=Transport(
            [
                _response(
                    headers={"content-type": "text/plain", "content-encoding": "gzip"},
                    chunks=(b"compressed",),
                )
            ]
        ),
        max_bytes=100,
        max_redirects=0,
    )
    with pytest.raises(WebFetchError):
        await fetcher.fetch(await fetcher.resolve("https://example.com"))


async def test_non_success_responseをcloseする() -> None:
    resolver = Resolver({"example.com": ("93.184.216.34",)})
    closed = CloseRecorder()
    response = PinnedResponse(503, {"content-type": "text/plain"}, _chunks(b"error"), closed)
    fetcher = SafeWebFetcher(
        resolver=resolver,
        transport=Transport([response]),
        max_bytes=100,
        max_redirects=0,
    )
    with pytest.raises(WebFetchError):
        await fetcher.fetch(await fetcher.resolve("https://example.com"))
    assert closed.called is True


@pytest.mark.parametrize(
    ("headers", "body"),
    [
        ({}, b"x"),
        ({"content-type": "application/json"}, b"{}"),
        ({"content-type": "text/plain; charset=shift_jis"}, b"x"),
        ({"content-type": "text/plain; charset=utf-8"}, b"\xff"),
    ],
)
async def test_malformed_unsupported_responseを拒否する(
    headers: Mapping[str, str], body: bytes
) -> None:
    resolver = Resolver({"example.com": ("93.184.216.34",)})
    fetcher = SafeWebFetcher(
        resolver=resolver,
        transport=Transport([_response(headers=headers, chunks=(body,))]),
        max_bytes=100,
        max_redirects=0,
    )
    with pytest.raises(WebFetchError):
        await fetcher.fetch(await fetcher.resolve("https://example.com"))


async def test_html_active_contentを除去しvisible_textをmaskする() -> None:
    resolver = Resolver({"example.com": ("93.184.216.34",)})
    html = (
        b"<h1>Hello</h1><script>steal()</script><style>secret</style>"
        b"<iframe>frame</iframe><object>object</object><math>formula</math>"
        b"<p>user@example.com</p>"
    )
    fetcher = SafeWebFetcher(
        resolver=resolver,
        transport=Transport(
            [_response(headers={"content-type": "text/html; charset=utf-8"}, chunks=(html,))]
        ),
        max_bytes=1000,
        max_redirects=0,
    )
    _, text = await fetcher.fetch(await fetcher.resolve("https://example.com"))
    assert text == "Hello\n[EMAIL]"
    assert all(value not in text for value in ("steal", "secret", "frame", "object", "formula"))
