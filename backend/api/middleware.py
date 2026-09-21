"""純粋なASGIミドルウェア。SSE（ストリーミング）を妨げないよう、BaseHTTPMiddlewareを使わない。"""

import time
import uuid

import structlog
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from api.deps import REISSUE_COOKIE_KEY
from core.logging import get_logger

_log = get_logger("hiromeru.request")
_MAX_REQUEST_ID_LENGTH = 64


class AuthCookieMiddleware:
    """認証済みRequestのResponseへ、アイドル期限を延長した認証Cookieを付与する。

    依存関係（`authenticated`）が scope に置いた `Set-Cookie` の値を、Response開始時に付ける。
    Responseを直接返すルートやSSEでも、Headerを付けられる。
    """

    def __init__(self, app: ASGIApp) -> None:
        """次のASGIアプリを受け取る。"""
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Response開始時にCookieを付与する。"""
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        async def send_with_cookie(message: Message) -> None:
            if message["type"] == "http.response.start":
                cookie = scope.get(REISSUE_COOKIE_KEY)
                if cookie:
                    MutableHeaders(scope=message).append("set-cookie", cookie)
            await send(message)

        await self._app(scope, receive, send_with_cookie)


class RequestContextMiddleware:
    """`request_id` を付与し、リクエストの結果を構造化ログへ出す。

    パスだけを記録する。クエリ文字列（検索語など）とBody・Cookieはログへ出さない。
    """

    def __init__(self, app: ASGIApp) -> None:
        """次のASGIアプリを受け取る。"""
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """リクエスト単位のログContextを設定する。"""
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        supplied = headers.get("x-request-id", "")
        request_id = supplied if 0 < len(supplied) <= _MAX_REQUEST_ID_LENGTH else uuid.uuid4().hex
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.perf_counter()
        status_code = 500

        async def send_with_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message).append("x-request-id", request_id)
            await send(message)

        try:
            await self._app(scope, receive, send_with_id)
        finally:
            _log.info(
                "request_finished",
                method=scope["method"],
                path=scope["path"],
                status=status_code,
                duration_ms=round((time.perf_counter() - started) * 1000),
            )
            structlog.contextvars.clear_contextvars()
