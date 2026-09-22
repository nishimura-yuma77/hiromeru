"""JSON Request BodyのMedia TypeとサイズをHTTP境界で検証する。"""

from fastapi import Request

from core.errors import AppError

MAX_REQUEST_BODY_BYTES = 4_500_000


def _invalid_body(message: str) -> AppError:
    return AppError("INVALID_ARGUMENT", message, field_errors=[])


async def read_json_body(request: Request) -> bytes:
    """JSON Bodyを上限までStreamで読み、全量Buffer前に超過を拒否する。"""
    content_type = request.headers.get("content-type", "")
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise _invalid_body("Content-Typeにapplication/jsonを指定してください。")

    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            advertised_size = int(content_length)
        except ValueError:
            advertised_size = 0
        if advertised_size > MAX_REQUEST_BODY_BYTES:
            raise _invalid_body("リクエストのサイズが上限を超えています。")

    size = 0
    chunks: list[bytes] = []
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_REQUEST_BODY_BYTES:
            raise _invalid_body("リクエストのサイズが上限を超えています。")
        chunks.append(chunk)
    return b"".join(chunks)
