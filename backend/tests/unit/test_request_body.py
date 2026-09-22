from collections.abc import AsyncIterator

import pytest
from starlette.requests import Request
from starlette.types import Message

from api.request_body import MAX_REQUEST_BODY_BYTES, read_json_body
from core.errors import AppError


def _request(headers: list[tuple[bytes, bytes]], chunks: list[bytes]) -> Request:
    iterator: AsyncIterator[bytes]

    async def body() -> AsyncIterator[bytes]:
        for chunk in chunks:
            yield chunk

    iterator = body()

    async def receive() -> Message:
        try:
            chunk = await anext(iterator)
        except StopAsyncIteration:
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.request", "body": chunk, "more_body": True}

    return Request({"type": "http", "method": "POST", "headers": headers}, receive)


async def test_JSON_Bodyはちょうど4_5MBまで読める() -> None:
    payload = b"{}" + b" " * (MAX_REQUEST_BODY_BYTES - 2)
    request = _request([(b"content-type", b"application/json; charset=utf-8")], [payload])

    assert await read_json_body(request) == payload


async def test_JSON_BodyはContent_Lengthなしでも上限を超えた時点で拒否する() -> None:
    request = _request(
        [(b"content-type", b"application/json")],
        [b" " * MAX_REQUEST_BODY_BYTES, b"x", b"unread"],
    )

    with pytest.raises(AppError) as info:
        await read_json_body(request)

    assert info.value.code == "INVALID_ARGUMENT"
    assert info.value.field_errors == []


async def test_JSON以外のMedia_TypeはBodyを読む前に拒否する() -> None:
    request = _request([(b"content-type", b"text/plain")], [b"{}"])

    with pytest.raises(AppError, match="application/json") as info:
        await read_json_body(request)

    assert info.value.code == "INVALID_ARGUMENT"
    assert info.value.field_errors == []
