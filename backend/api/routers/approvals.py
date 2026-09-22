"""承認API（施策の登録・更新、X投稿の公開。API_DESIGN 3.1、4.1）。"""

from typing import Annotated

from fastapi import APIRouter, Header, Path, Request
from fastapi.responses import JSONResponse

from api.deps import Context, CsrfProtected
from api.request_body import read_json_body
from services.approval import ApprovalOutcome
from services.campaign_approval import CampaignApprovalService
from services.x_post_approval import XPostApprovalService

router = APIRouter(prefix="/api/v1/agent-sessions/{session_id}", tags=["approvals"])

SessionId = Annotated[int, Path(gt=0)]
IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key")]


def _respond(outcome: ApprovalOutcome) -> JSONResponse:
    headers = (
        {"Retry-After": str(outcome.retry_after_seconds)}
        if outcome.retry_after_seconds is not None
        else None
    )
    return JSONResponse(outcome.body, status_code=outcome.http_status, headers=headers)


@router.post("/x/posts")
async def publish_x_post(
    session_id: SessionId,
    request: Request,
    ctx: Context,
    auth: CsrfProtected,
    idempotency_key: IdempotencyKey = None,
) -> JSONResponse:
    """最終承認済みの投稿内容をXへ投稿する。`Idempotency-Key` 必須。"""
    outcome = await XPostApprovalService(ctx).publish(
        auth, session_id, lambda: read_json_body(request), idempotency_key
    )
    return _respond(outcome)


@router.post("/campaigns")
async def upsert_campaign(
    session_id: SessionId,
    request: Request,
    ctx: Context,
    auth: CsrfProtected,
    idempotency_key: IdempotencyKey = None,
) -> JSONResponse:
    """承認された施策のフォーム値を、新規保存または全項目上書きで保存する。

    `Idempotency-Key` 必須。
    """
    outcome = await CampaignApprovalService(ctx).upsert(
        auth, session_id, lambda: read_json_body(request), idempotency_key
    )
    return _respond(outcome)
