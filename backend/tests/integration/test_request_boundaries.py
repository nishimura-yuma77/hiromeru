import asyncio
import json
import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from api.main import create_app
from api.request_body import MAX_REQUEST_BODY_BYTES
from models import AgentTurn, ApiIdempotencyRequest
from repositories.agent import SessionRepository
from repositories.database import SessionLocal
from services.context import ServiceContext
from tests.support.client import Account, campaign_body, post_body
from tests.support.fakes import FakeAgentRunner, FakeEmbedding, FakeXApi, FixedClock


def _json_with_size(body: dict[str, object], size: int) -> bytes:
    encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
    assert len(encoded) <= size
    return encoded + b" " * (size - len(encoded))


async def _chunks(payload: bytes) -> AsyncIterator[bytes]:
    chunk_size = 64 * 1024
    for offset in range(0, len(payload), chunk_size):
        yield payload[offset : offset + chunk_size]


async def _approval_counts(session_id: int) -> tuple[int, int]:
    async with SessionLocal() as session:
        turns = await session.scalar(
            select(func.count()).select_from(AgentTurn).where(AgentTurn.session_id == session_id)
        )
        requests = await session.scalar(
            select(func.count())
            .select_from(ApiIdempotencyRequest)
            .where(ApiIdempotencyRequest.session_id == session_id)
        )
    return int(turns or 0), int(requests or 0)


async def _short_timeout_client(
    account: Account, ctx: ServiceContext, timeout_seconds: float = 0.05
) -> AsyncClient:
    ctx.settings.request_timeout_seconds = timeout_seconds
    return AsyncClient(
        transport=ASGITransport(app=create_app(ctx), raise_app_exceptions=False),
        base_url="http://test",
        headers=dict(account.client.headers),
        cookies=account.client.cookies,
    )


async def test_JSON_Media_Type以外は共通Errorで拒否し承認履歴を作らない(
    account: Account, embedding: FakeEmbedding
) -> None:
    session_id = await account.create_session()

    response = await account.client.post(
        f"/api/v1/agent-sessions/{session_id}/campaigns",
        content=json.dumps(campaign_body()).encode(),
        headers={"Content-Type": "text/plain", "Idempotency-Key": str(uuid.uuid4())},
    )

    assert response.status_code == 400
    assert response.json()["error"] == {
        "code": "INVALID_ARGUMENT",
        "message": "Content-Typeにapplication/jsonを指定してください。",
        "retryable": False,
        "agent_turn_id": None,
        "field_errors": [],
    }
    assert await _approval_counts(session_id) == (0, 0)
    assert embedding.calls == []


async def test_JSON_Media_Typeの大文字とcharsetを許可する(account: Account) -> None:
    session_id = await account.create_session()

    response = await account.client.post(
        f"/api/v1/agent-sessions/{session_id}/campaigns",
        content=json.dumps(campaign_body()).encode(),
        headers={
            "Content-Type": "Application/JSON; charset=utf-8",
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )

    assert response.status_code == 201


async def test_Bodyがちょうど4_5MBなら受け付ける(account: Account) -> None:
    session_id = await account.create_session()
    payload = _json_with_size(campaign_body(), MAX_REQUEST_BODY_BYTES)

    response = await account.client.post(
        f"/api/v1/agent-sessions/{session_id}/campaigns",
        content=payload,
        headers={"Content-Type": "application/json", "Idempotency-Key": str(uuid.uuid4())},
    )

    assert len(payload) == MAX_REQUEST_BODY_BYTES
    assert response.status_code == 201


async def test_Content_Lengthが4_5MBを超えるとBodyを読まず承認履歴を作らない(
    account: Account, embedding: FakeEmbedding
) -> None:
    session_id = await account.create_session()
    consumed = False

    async def content() -> AsyncIterator[bytes]:
        nonlocal consumed
        consumed = True
        yield b"{}"

    response = await account.client.post(
        f"/api/v1/agent-sessions/{session_id}/campaigns",
        content=content(),
        headers={
            "Content-Type": "application/json",
            "Content-Length": str(MAX_REQUEST_BODY_BYTES + 1),
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_ARGUMENT"
    assert response.json()["error"]["field_errors"] == []
    assert consumed is False
    assert await _approval_counts(session_id) == (0, 0)
    assert embedding.calls == []


async def test_Content_Lengthなしで4_5MBを超えてもXを呼ばず承認履歴を作らない(
    account: Account, x_api: FakeXApi
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign()
    before = await _approval_counts(session_id)
    payload = _json_with_size(post_body(campaign_id), MAX_REQUEST_BODY_BYTES + 1)

    response = await account.client.post(
        f"/api/v1/agent-sessions/{session_id}/x/posts",
        content=_chunks(payload),
        headers={"Content-Type": "application/json", "Idempotency-Key": str(uuid.uuid4())},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_ARGUMENT"
    assert response.json()["error"]["field_errors"] == []
    assert await _approval_counts(session_id) == before
    assert x_api.calls == []


async def test_Request_Timeout_DB停止時は本文なし504(
    account: Account, ctx: ServiceContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_id = await account.create_session()
    started = asyncio.Event()

    async def stalled(*_args: object, **_kwargs: object) -> None:
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(SessionRepository, "get_parent", stalled)
    async with await _short_timeout_client(account, ctx) as client:
        response = await client.post(
            f"/api/v1/agent-sessions/{session_id}/campaigns",
            json=campaign_body(),
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )

    assert started.is_set()
    assert response.status_code == 504
    assert response.content == b""


async def test_Request_Timeout_外部Client停止時は本文なし504(
    account: Account, ctx: ServiceContext, embedding: FakeEmbedding
) -> None:
    session_id = await account.create_session()
    embedding.block_next = asyncio.Event()
    async with await _short_timeout_client(account, ctx) as client:
        response = await client.post(
            f"/api/v1/agent-sessions/{session_id}/campaigns",
            json=campaign_body(),
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )

    assert embedding.blocked.is_set()
    assert response.status_code == 504
    assert response.content == b""


async def test_Request_Timeout_Agent停止時は本文なし504(
    account: Account, ctx: ServiceContext, agent: FakeAgentRunner
) -> None:
    session_id = await account.create_session()
    agent.hang = True
    async with await _short_timeout_client(account, ctx) as client:
        response = await client.post(
            f"/api/v1/agent-sessions/{session_id}/turns", json={"message": "止める"}
        )

    assert agent.started.is_set()
    assert response.status_code == 504
    assert response.content == b""


async def test_Request_Timeout_X送信中断後は同じキーで結果不明へ復旧し再投稿しない(
    account: Account, ctx: ServiceContext, x_api: FakeXApi, clock: FixedClock
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign()
    x_api.gate = asyncio.Event()
    key = str(uuid.uuid4())
    body = post_body(campaign_id)

    async with await _short_timeout_client(account, ctx) as client:
        timed_out = await client.post(
            f"/api/v1/agent-sessions/{session_id}/x/posts",
            json=body,
            headers={"Idempotency-Key": key},
        )
    in_progress = await account.publish_post(session_id, body, key)
    clock.advance(331)
    recovered = await account.publish_post(session_id, body, key)

    assert x_api.started.is_set()
    assert timed_out.status_code == 504
    assert timed_out.content == b""
    assert in_progress.status_code == 409
    assert in_progress.json()["error"]["code"] == "IDEMPOTENCY_REQUEST_IN_PROGRESS"
    assert recovered.status_code == 504
    assert recovered.json()["error"]["code"] == "X_POST_OUTCOME_UNKNOWN"
    assert recovered.json()["error"]["retryable"] is False
    assert len(x_api.calls) == 1
