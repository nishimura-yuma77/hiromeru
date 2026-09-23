import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from domain.enums import ApiOperation
from models import ApiIdempotencyRequest
from repositories.database import SessionLocal
from repositories.posts import PostRepository
from services.context import ServiceContext
from services.x_post_recovery import XPostRecoveryService
from tests.support.client import Account, post_body
from tests.support.fakes import FakeXApi


async def _request(account: Account, key: str) -> ApiIdempotencyRequest:
    async with SessionLocal() as session:
        return (
            await session.execute(
                select(ApiIdempotencyRequest).where(
                    ApiIdempotencyRequest.marketer_id == account.marketer_id,
                    ApiIdempotencyRequest.operation == ApiOperation.PUBLISH_X_POST,
                    ApiIdempotencyRequest.idempotency_key == uuid.UUID(key),
                )
            )
        ).scalar_one()


async def _turn(account: Account, session_id: int, turn_id: int | None) -> dict[str, Any]:
    assert turn_id is not None
    response = await account.client.get(
        f"/api/v1/agent-sessions/{session_id}/turns/{turn_id}"
    )
    assert response.status_code == 200
    return response.json()["data"]


async def test_campaign承認とchatのapproval_stateを公開する(account: Account) -> None:
    session_id = await account.create_session()
    await account.create_campaign(session_id)
    chat = await account.client.post(
        f"/api/v1/agent-sessions/{session_id}/turns", json={"message": "確認"}
    )
    history = (await account.client.get(f"/api/v1/agent-sessions/{session_id}")).json()[
        "data"
    ]["turns"]
    approval = next(turn for turn in history if turn["kind"] == "approval")

    assert approval["approval_state"] == {
        "operation": "upsert_campaign",
        "status": "succeeded",
        "external_effect_started": False,
        "external_succeeded": False,
        "recovery": None,
    }
    assert chat.json()["data"]["approval_state"] is None


async def test_X結果不明はmanual_reconciliationで解決後に確定状態を返す(
    account: Account, x_api: FakeXApi, ctx: ServiceContext
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    key = str(uuid.uuid4())
    x_api.outcome = "unknown"
    response = await account.publish_post(session_id, post_body(campaign_id), key)
    row = await _request(account, key)

    unresolved = await _turn(account, session_id, row.agent_turn_id)
    assert response.status_code == 504
    assert unresolved["approval_state"] == {
        "operation": "publish_x_post",
        "status": "outcome_unknown",
        "external_effect_started": True,
        "external_succeeded": False,
        "recovery": "manual_reconciliation",
    }
    assert "external_result" not in str(unresolved)

    await XPostRecoveryService(ctx).resolve_not_posted(row.id)
    resolved = await _turn(account, session_id, row.agent_turn_id)
    assert resolved["approval_state"]["status"] == "failed"
    assert resolved["approval_state"]["recovery"] is None


async def test_X保存待ちはexternal本文なしでretry_same_keyを返す(
    account: Account,
    x_api: FakeXApi,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del x_api
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    key = str(uuid.uuid4())
    original = PostRepository.insert_published

    async def failing(self: PostRepository, *args: Any, **kwargs: Any) -> Any:
        del self, args, kwargs
        raise OperationalError("INSERT", {}, Exception("db down"))

    monkeypatch.setattr(PostRepository, "insert_published", failing)
    response = await account.publish_post(session_id, post_body(campaign_id), key)
    monkeypatch.setattr(PostRepository, "insert_published", original)
    row = await _request(account, key)

    projected = await _turn(account, session_id, row.agent_turn_id)
    assert response.status_code == 500
    assert projected["approval_state"] == {
        "operation": "publish_x_post",
        "status": "processing",
        "external_effect_started": True,
        "external_succeeded": True,
        "recovery": "retry_same_key",
    }
    assert "external_result" not in str(projected)
    assert [item["type"] for item in projected["items"]] == ["approval_action"]
