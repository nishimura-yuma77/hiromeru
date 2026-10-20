"""E2E専用API（E2E_TEST_SPEC 4.1、5章）。`E2E_MODE=true` のときだけ登録する。

事前条件の準備、外部障害の注入、事後結果の確認だけに使い、業務APIの主操作を代替しない。
本番・プレビューでは設定検証で `E2E_MODE` を拒否するため、このRouterは公開されない。
"""

import re
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field

from api.deps import Context
from api.request_body import read_json_body
from api.responses import ok
from clients.email import FakeEmailClient
from core.clock import AdjustableClock
from core.errors import AppError
from domain.requests import StrictModel
from services.auth_service import AuthService, CompanySetupError
from services.context import ServiceContext
from services.validation import parse_json_object, validate_model

router = APIRouter(prefix="/api/e2e", tags=["e2e"])

_LINK = re.compile(r"https?://\S+/invitations/accept\?token=[A-Za-z0-9_-]+")

type Outcome = Literal["ok", "throttled", "rejected", "unknown", "interrupted"]


class CompanySetupRequest(StrictModel):
    """初期設定スクリプトと同じ入力。"""

    company: str
    name: str
    email: str
    password: str


class EmailOutcomesRequest(StrictModel):
    """次の送信から順に返すSES Fakeの応答。"""

    outcomes: list[Outcome] = Field(max_length=20)


class ClockRequest(StrictModel):
    """時計を進める秒数。"""

    advance_seconds: Annotated[float, Field(gt=0, le=30 * 24 * 3600)]


def _email_client(ctx: ServiceContext) -> FakeEmailClient:
    client = ctx.email_client
    if not isinstance(client, FakeEmailClient):
        raise AppError("INTERNAL_ERROR", "E2EではSES Fakeを使ってください。")
    return client


def _clock(ctx: ServiceContext) -> AdjustableClock:
    clock = ctx.clock
    if not isinstance(clock, AdjustableClock):
        raise AppError("INTERNAL_ERROR", "E2Eでは進められる時計を使ってください。")
    return clock


@router.post("/companies")
async def setup_company(request: Request, ctx: Context) -> JSONResponse:
    """初期設定スクリプトと同じ処理で、会社と責任者を登録する。"""
    body = validate_model(CompanySetupRequest, parse_json_object(await read_json_body(request)))
    try:
        user = await AuthService(ctx).create_company(
            company_name=body.company, name=body.name, email=body.email, password=body.password
        )
    except CompanySetupError as error:
        return JSONResponse(
            {"success": False, "data": None, "error": {"message": str(error)}}, status_code=409
        )
    return ok({"user_id": user.user_id, "company_id": user.company_id}, status_code=201)


@router.get("/emails")
async def list_emails(ctx: Context, to: Annotated[str, Query(min_length=1)]) -> JSONResponse:
    """宛先ごとに、SES Fakeが受け付けた送信内容と招待リンクを返す。"""
    messages = [message for message in _email_client(ctx).sent if message.to == to.lower()]
    return ok(
        {
            "count": len(messages),
            "messages": [
                {
                    "subject": message.subject,
                    "link": match.group(0) if (match := _LINK.search(message.body)) else None,
                }
                for message in messages
            ],
        }
    )


@router.post("/email-outcomes")
async def reserve_email_outcomes(request: Request, ctx: Context) -> JSONResponse:
    """次の送信から順に返すSES Fakeの応答を予約する。"""
    body = validate_model(EmailOutcomesRequest, parse_json_object(await read_json_body(request)))
    client = _email_client(ctx)
    client.outcomes = list(body.outcomes)
    return ok({"outcomes": client.outcomes})


@router.post("/clock")
async def advance_clock(request: Request, ctx: Context) -> JSONResponse:
    """時計を進める。招待リンクの期限切れや認証Cookieのアイドル期限を再現する。"""
    body = validate_model(ClockRequest, parse_json_object(await read_json_body(request)))
    clock = _clock(ctx)
    clock.advance(body.advance_seconds)
    return ok({"now": clock.now().isoformat()})


@router.post("/reset")
async def reset(ctx: Context) -> JSONResponse:
    """時計と、SES Fakeの予約した応答を戻す。送信記録は宛先で区別するため残す。"""
    _clock(ctx).reset()
    _email_client(ctx).outcomes = []
    return ok(None)
