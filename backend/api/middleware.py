"""純粋なASGIミドルウェア。SSE（ストリーミング）を妨げないよう、BaseHTTPMiddlewareを使わない。"""

import asyncio
import time
import uuid

import structlog
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from api.deps import REISSUE_COOKIE_KEY
from core.logging import get_logger

_log = get_logger("hiromeru.request")
_MAX_REQUEST_ID_LENGTH = 64
REQUEST_DEADLINE_KEY = "hiromeru.request_deadline"


class RequestTimeoutMiddleware:
    """Request全体へDeadlineを適用し、開始前のTimeoutを本文なし504へ変換する。"""

    def __init__(self, app: ASGIApp, timeout_seconds: float) -> None:
        """次のASGIアプリとRequest上限時間を受け取る。"""
        self._app = app
        self._timeout_seconds = timeout_seconds

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """HTTP Requestを共通Deadline内で実行する。"""
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        response_start_attempted = False
        response_started = False
        response_complete_attempted = False
        response_complete = False

        async def send_tracked(message: Message) -> None:
            nonlocal response_complete, response_complete_attempted
            nonlocal response_start_attempted, response_started
            if message["type"] == "http.response.start":
                response_start_attempted = True
                await send(message)
                response_started = True
                return
            is_final_body = message["type"] == "http.response.body" and not message.get(
                "more_body", False
            )
            if is_final_body:
                response_complete_attempted = True
            await send(message)
            if is_final_body:
                response_complete = True

        request_deadline = asyncio.get_running_loop().time() + self._timeout_seconds
        scope[REQUEST_DEADLINE_KEY] = request_deadline
        deadline = asyncio.timeout_at(request_deadline)
        try:
            async with deadline:
                await self._app(scope, receive, send_tracked)
        except TimeoutError:
            if not deadline.expired():
                raise
            if response_complete or response_complete_attempted:
                return
            if not response_start_attempted:
                await send({"type": "http.response.start", "status": 504, "headers": []})
                await send({"type": "http.response.body", "body": b""})
            elif response_started:
                await send({"type": "http.response.body", "body": b""})


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
