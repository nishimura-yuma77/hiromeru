"""DNS pinningとredirect再検証を行うWeb取得client。"""

import asyncio
import ipaddress
import socket
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Protocol
from urllib.parse import urljoin, urlsplit

import httpx

from core.masking import mask_text

_SAFE_HEADERS = {
    "Accept": "text/html,text/plain;q=0.9",
    "Accept-Encoding": "identity",
    "User-Agent": "hiromeru-web-fetch/1",
}
_REDIRECTS = frozenset({301, 302, 303, 307, 308})
_ACTIVE_TAGS = frozenset(
    {
        "script",
        "style",
        "noscript",
        "template",
        "iframe",
        "object",
        "embed",
        "svg",
        "math",
        "canvas",
    }
)
_MAX_URL_LENGTH = 8_000


class UnsafeUrlError(Exception):
    """URLまたは解決先が外部公開先として安全でない。"""


class WebFetchError(Exception):
    """取得・応答形式エラー。"""


class ContentTooLargeError(WebFetchError):
    """応答が設定上限を超えた。"""


class Resolver(Protocol):
    """名前解決境界。"""

    async def resolve(self, host: str, port: int) -> tuple[str, ...]:
        """hostの全IP回答を返す。"""
        ...


class SystemResolver:
    """OS resolverを非同期利用する。"""

    async def resolve(self, host: str, port: int) -> tuple[str, ...]:
        """OSから全stream接続候補を返す。"""
        loop = asyncio.get_running_loop()
        rows = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        return tuple(dict.fromkeys(str(row[4][0]) for row in rows))


@dataclass(frozen=True)
class ResolvedUrl:
    """検証済みURLと固定接続先。"""

    url: str
    host: str
    port: int
    ips: tuple[str, ...]


@dataclass(frozen=True)
class PinnedResponse:
    """接続先固定transportのstreaming応答。"""

    status_code: int
    headers: Mapping[str, str]
    chunks: AsyncIterator[bytes]
    close: Callable[[], Awaitable[None]]


class PinnedTransport(Protocol):
    """検証済みIPだけへ接続するtransport。"""

    async def request(self, target: ResolvedUrl, headers: Mapping[str, str]) -> PinnedResponse:
        """再名前解決せずGETする。"""
        ...


class WebFetcher(Protocol):
    """Web Toolが利用するURL解決・本文取得境界。"""

    async def resolve(self, url: str) -> ResolvedUrl:
        """URLを検証して取得用表現へ変換する。"""
        ...

    async def fetch(self, initial: ResolvedUrl) -> tuple[str, str]:
        """検証済みURLの最終URLと本文を返す。"""
        ...


class FakeWebFetcher:
    """DNS・HTTP通信を行わず固定本文を返すWeb取得Fake。"""

    async def resolve(self, url: str) -> ResolvedUrl:
        """HTTPS URLの構文だけを検証し、外部名前解決を行わない。"""
        try:
            parts = urlsplit(url)
            host = parts.hostname
            port = parts.port or 443
        except ValueError as error:
            raise UnsafeUrlError from error
        if (
            len(url) > _MAX_URL_LENGTH
            or any(ord(character) < 32 or ord(character) == 127 for character in url)
            or parts.scheme.lower() != "https"
            or host is None
            or parts.username is not None
            or parts.password is not None
            or port != 443
            or not parts.netloc
            or "\\" in parts.netloc
        ):
            raise UnsafeUrlError
        try:
            normalized_host = host.encode("idna").decode("ascii").lower()
        except UnicodeError as error:
            raise UnsafeUrlError from error
        display_host = f"[{normalized_host}]" if ":" in normalized_host else normalized_host
        normalized = parts._replace(scheme="https", netloc=display_host, fragment="").geturl()
        return ResolvedUrl(normalized, normalized_host, port, ("93.184.216.34",))

    async def fetch(self, initial: ResolvedUrl) -> tuple[str, str]:
        """外部へ接続せず決定的な本文を返す。"""
        return initial.url, "Fake web content for external-client isolation."


class HttpxPinnedTransport:
    """httpxの接続URLをIPへ固定しHost/TLS SNIを元hostへ保つ。"""

    def __init__(
        self, timeout_seconds: float, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        """timeoutとテスト可能な下位transportを保持する。"""
        self._timeout = timeout_seconds
        self._transport = transport

    async def request(self, target: ResolvedUrl, headers: Mapping[str, str]) -> PinnedResponse:
        """検証済み先頭IPへHost/SNIを維持して接続する。"""
        # URL hostがIPなのでhttpcoreはDNSを行わない。sni_hostnameはhttpcoreのTLS contract。
        pinned_url = httpx.URL(target.url).copy_with(host=target.ips[0])
        host_header = target.host if target.port == 443 else f"{target.host}:{target.port}"
        client = httpx.AsyncClient(
            timeout=self._timeout,
            trust_env=False,
            follow_redirects=False,
            transport=self._transport,
        )
        try:
            request_headers = {
                key: value
                for key, value in headers.items()
                if key.lower() in {"accept", "user-agent"}
            }
            request_headers.update({"Accept-Encoding": "identity", "Host": host_header})
            request = client.build_request("GET", pinned_url, headers=request_headers)
            request.extensions["sni_hostname"] = target.host
            response = await client.send(request, stream=True)
        except Exception:
            await client.aclose()
            raise

        async def chunks() -> AsyncIterator[bytes]:
            try:
                # 圧縮爆弾を展開しない。Fetcher側でcontent-encodingを拒否する。
                async for chunk in response.aiter_raw():
                    yield chunk
            finally:
                await response.aclose()
                await client.aclose()

        async def close() -> None:
            await response.aclose()
            await client.aclose()

        return PinnedResponse(response.status_code, response.headers, chunks(), close)


def _public_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_global and not address.is_multicast


async def resolve_url(url: str, resolver: Resolver) -> ResolvedUrl:
    """HTTPS URLを正規化し、全DNS回答がglobalであることを検証する。"""
    if len(url) > _MAX_URL_LENGTH or any(
        ord(character) < 32 or ord(character) == 127 for character in url
    ):
        raise UnsafeUrlError
    try:
        parts = urlsplit(url)
        port = parts.port or 443
        host = parts.hostname
    except ValueError as error:
        raise UnsafeUrlError from error
    if (
        parts.scheme.lower() != "https"
        or host is None
        or parts.username is not None
        or parts.password is not None
        or port != 443
        or not parts.netloc
        or "\\" in parts.netloc
    ):
        raise UnsafeUrlError
    try:
        host = host.encode("idna").decode("ascii").lower()
    except UnicodeError as error:
        raise UnsafeUrlError from error
    try:
        literal = ipaddress.ip_address(host)
        ips = (str(literal),)
    except ValueError:
        try:
            ips = await resolver.resolve(host, port)
        except Exception as error:
            raise WebFetchError from error
    if not ips or any(not _public_ip(ip) for ip in ips):
        raise UnsafeUrlError
    normalized_host = f"[{host}]" if ":" in host else host
    normalized = parts._replace(scheme="https", netloc=normalized_host, fragment="").geturl()
    return ResolvedUrl(normalized, host, port, ips)


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._hidden = 0
        self.values: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.lower() in _ACTIVE_TAGS:
            self._hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in _ACTIVE_TAGS and self._hidden:
            self._hidden -= 1

    def handle_data(self, data: str) -> None:
        if not self._hidden and data.strip():
            self.values.append(data.strip())


class SafeWebFetcher:
    """各redirect hopを再検証してvisible textだけを返す。"""

    def __init__(
        self, *, resolver: Resolver, transport: PinnedTransport, max_bytes: int, max_redirects: int
    ) -> None:
        """SSRF・response上限依存を保持する。"""
        self._resolver = resolver
        self._transport = transport
        self._max_bytes = max_bytes
        self._max_redirects = max_redirects

    async def resolve(self, url: str) -> ResolvedUrl:
        """初回URLを同じresolver policyで検証する。"""
        return await resolve_url(url, self._resolver)

    async def fetch(self, initial: ResolvedUrl) -> tuple[str, str]:
        """検証済みURLを取得し、最終URLと安全なtextを返す。"""
        target = initial
        visited: set[str] = set()
        for hop in range(self._max_redirects + 1):
            if target.url in visited:
                raise UnsafeUrlError
            visited.add(target.url)
            try:
                response = await self._transport.request(target, _SAFE_HEADERS)
            except Exception as error:
                raise WebFetchError from error
            if response.status_code in _REDIRECTS:
                location = response.headers.get("location")
                await response.close()
                if not location or hop == self._max_redirects:
                    raise UnsafeUrlError
                target = await resolve_url(urljoin(target.url, location), self._resolver)
                continue
            if response.status_code < 200 or response.status_code >= 300:
                await response.close()
                raise WebFetchError
            try:
                body = await self._read(response)
            except Exception:
                await response.close()
                raise
            return target.url, self._text(body, response.headers.get("content-type"))
        raise UnsafeUrlError

    async def _read(self, response: PinnedResponse) -> bytes:
        content_encoding = response.headers.get("content-encoding", "identity").lower().strip()
        if content_encoding not in {"", "identity"}:
            raise WebFetchError
        length = response.headers.get("content-length")
        try:
            if length is not None:
                parsed_length = int(length)
                if parsed_length < 0:
                    raise WebFetchError
                if parsed_length > self._max_bytes:
                    raise ContentTooLargeError
        except ValueError as error:
            raise WebFetchError from error
        body = bytearray()
        async for chunk in response.chunks:
            if len(body) + len(chunk) > self._max_bytes:
                raise ContentTooLargeError
            body.extend(chunk)
        return bytes(body)

    @staticmethod
    def _text(body: bytes, content_type: str | None) -> str:
        if content_type is None:
            raise WebFetchError
        media, *parameters = [part.strip() for part in content_type.split(";")]
        if media.lower() not in {"text/html", "text/plain"}:
            raise WebFetchError
        charset = "utf-8"
        for parameter in parameters:
            if parameter.lower().startswith("charset="):
                charset = parameter.split("=", 1)[1].strip('"').lower()
        if charset not in {"utf-8", "utf8", "us-ascii", "iso-8859-1"}:
            raise WebFetchError
        try:
            decoded = body.decode(charset, errors="strict")
        except (LookupError, UnicodeDecodeError) as error:
            raise WebFetchError from error
        if media.lower() == "text/plain":
            return mask_text(decoded)
        parser = _VisibleTextParser()
        try:
            parser.feed(decoded)
            parser.close()
        except Exception as error:
            raise WebFetchError from error
        return mask_text("\n".join(parser.values))
