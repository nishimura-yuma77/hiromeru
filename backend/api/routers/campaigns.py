"""施策API（API_DESIGN 4.2、6.2、6.3）。"""

from typing import Annotated

from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import JSONResponse

from api.deps import Authenticated, Context, CsrfProtected
from api.queries import parse_query_datetime
from api.request_body import read_json_body
from api.responses import ok
from api.serializers import (
    serialize_campaign_detail,
    serialize_campaign_edit,
    serialize_campaign_list,
)
from domain.constants import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT
from domain.requests import CampaignEditRequest
from services.campaign_service import CampaignService
from services.validation import parse_json_object, validate_model

router = APIRouter(prefix="/api/v1/campaigns", tags=["campaigns"])

CampaignId = Annotated[int, Path(gt=0)]


@router.get("")
async def list_campaigns(
    ctx: Context,
    auth: Authenticated,
    query: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
    cursor: str | None = None,
) -> JSONResponse:
    """施策を新しい順、または意味検索で返す。"""
    view = await CampaignService(ctx).list(
        auth,
        query=query,
        created_from=parse_query_datetime(created_from, "created_from"),
        created_to=parse_query_datetime(created_to, "created_to"),
        limit=limit,
        cursor=cursor,
    )
    return ok(serialize_campaign_list(view))


@router.get("/{campaign_id}")
async def get_campaign(campaign_id: CampaignId, ctx: Context, auth: Authenticated) -> JSONResponse:
    """施策の全項目と、紐づく投稿・記憶、計測の集計を返す。"""
    return ok(serialize_campaign_detail(await CampaignService(ctx).detail(auth, campaign_id)))


@router.put("/{campaign_id}")
async def edit_campaign(
    campaign_id: CampaignId, request: Request, ctx: Context, auth: CsrfProtected
) -> JSONResponse:
    """保存済みの施策を、フォームの内容で全項目上書きする。Agent履歴・冪等性は使わない。"""
    body = validate_model(CampaignEditRequest, parse_json_object(await read_json_body(request)))
    return ok(serialize_campaign_edit(await CampaignService(ctx).edit(auth, campaign_id, body)))
