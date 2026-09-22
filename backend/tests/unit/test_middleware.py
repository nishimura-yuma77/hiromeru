import asyncio

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from api.middleware import REQUEST_DEADLINE_KEY, RequestTimeoutMiddleware


def _scope() -> Scope:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/test",
        "raw_path": b"/test",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 1),
        "server": ("test", 80),
    }


async def _receive() -> Message:
    return {"type": "http.disconnect"}


async def test_Request_Timeout_Response開始前は本文なし504を返す() -> None:
    async def stalled_app(scope: Scope, receive: Receive, send: Send) -> None:
        del scope, receive, send
        await asyncio.Event().wait()

    messages: list[Message] = []

    async def record(message: Message) -> None:
        messages.append(message)

    middleware = RequestTimeoutMiddleware(stalled_app, timeout_seconds=0.01)

    await middleware(_scope(), _receive, record)

    assert messages == [
        {"type": "http.response.start", "status": 504, "headers": []},
        {"type": "http.response.body", "body": b""},
    ]


async def test_Request_Timeout_SSEをBufferせず共通Deadlineを渡す() -> None:
    gate = asyncio.Event()
    messages: asyncio.Queue[Message] = asyncio.Queue()

    async def streaming_app(scope: Scope, receive: Receive, send: Send) -> None:
        del receive
        assert isinstance(scope[REQUEST_DEADLINE_KEY], float)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"first", "more_body": True})
        await gate.wait()
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    app: ASGIApp = streaming_app
    middleware = RequestTimeoutMiddleware(app, timeout_seconds=1)
    running = asyncio.create_task(middleware(_scope(), _receive, messages.put))

    assert await asyncio.wait_for(messages.get(), 0.1) == {
        "type": "http.response.start",
        "status": 200,
        "headers": [],
    }
    assert await asyncio.wait_for(messages.get(), 0.1) == {
        "type": "http.response.body",
        "body": b"first",
        "more_body": True,
    }
    assert not running.done()
    gate.set()
    await running


async def test_Request_Timeout_完了Body送信後は追加Bodyを送らない() -> None:
    messages: list[Message] = []

    async def completed_then_stalled(scope: Scope, receive: Receive, send: Send) -> None:
        del scope, receive
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"done", "more_body": False})
        await asyncio.Event().wait()

    async def record(message: Message) -> None:
        messages.append(message)

    middleware = RequestTimeoutMiddleware(completed_then_stalled, timeout_seconds=0.01)

    await middleware(_scope(), _receive, record)

    assert messages == [
        {"type": "http.response.start", "status": 200, "headers": []},
        {"type": "http.response.body", "body": b"done", "more_body": False},
    ]


async def test_Request_Timeout_Response開始送信中は不正なBodyを追加しない() -> None:
    messages: list[Message] = []

    async def immediate_response(scope: Scope, receive: Receive, send: Send) -> None:
        del scope, receive
        await send({"type": "http.response.start", "status": 200, "headers": []})

    async def stalled_send(message: Message) -> None:
        messages.append(message)
        await asyncio.Event().wait()

    middleware = RequestTimeoutMiddleware(immediate_response, timeout_seconds=0.01)

    await middleware(_scope(), _receive, stalled_send)

    assert messages == [{"type": "http.response.start", "status": 200, "headers": []}]
