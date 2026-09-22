"""ログイン済みクライアントと、施策・投稿を作る操作の補助。"""

import uuid
from dataclasses import dataclass
from typing import Any

from httpx import AsyncClient, Response


@dataclass
class Account:
    """ログイン済みのマーケター。Origin と CSRF ヘッダーは `client` に設定済み。"""

    client: AsyncClient
    marketer_id: int
    company_id: int
    email: str
    csrf: str

    async def create_session(self) -> int:
        """親Sessionを作り、`session_id` を返す。"""
        response = await self.client.post("/api/v1/agent-sessions")
        assert response.status_code == 201, response.text
        return int(response.json()["data"]["session_id"])

    async def upsert_campaign(
        self, session_id: int, body: dict[str, Any], key: str | None = None
    ) -> Response:
        """施策を登録・更新する。"""
        return await self.client.post(
            f"/api/v1/agent-sessions/{session_id}/campaigns",
            json=body,
            headers={"Idempotency-Key": key or str(uuid.uuid4())},
        )

    async def publish_post(
        self, session_id: int, body: dict[str, Any], key: str | None = None
    ) -> Response:
        """X投稿を公開する。"""
        return await self.client.post(
            f"/api/v1/agent-sessions/{session_id}/x/posts",
            json=body,
            headers={"Idempotency-Key": key or str(uuid.uuid4())},
        )

    async def create_campaign(self, session_id: int | None = None, **overrides: str) -> int:
        """施策を新規作成し、`id` を返す。"""
        sid = session_id if session_id is not None else await self.create_session()
        response = await self.upsert_campaign(sid, campaign_body(**overrides))
        assert response.status_code == 201, response.text
        return int(response.json()["data"]["id"])


def campaign_body(**overrides: Any) -> dict[str, Any]:
    """施策の既定のBody。"""
    body: dict[str, Any] = {
        "title": "春の新規フォロワー獲得",
        "target_profile": "20代の会社員",
        "background": "春の新生活シーズン",
        "objective": "資料請求を増やす",
        "plan": "週3回、事例を投稿する",
    }
    body.update(overrides)
    return body


def post_body(campaign_id: int, **overrides: Any) -> dict[str, Any]:
    """X投稿の既定のBody。"""
    body: dict[str, Any] = {
        "campaign_id": campaign_id,
        "body": "春の新生活を応援します。資料はこちら",
        "landing_url": "https://example.com/lp",
    }
    body.update(overrides)
    return body
