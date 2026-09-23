"""投稿・計測の参照API（API_DESIGN 6.4〜6.6）。"""

from typing import Annotated

from fastapi import APIRouter, Path, Query
from fastapi.responses import JSONResponse

from api.deps import Authenticated, Context
from api.queries import parse_query_datetime
from api.responses import ok
from api.serializers import serialize_metrics_report, serialize_post_detail, serialize_post_list
from domain.constants import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT
from services.metrics_service import MetricsService
from services.post_service import PostService

router = APIRouter(prefix="/api/v1", tags=["posts"])


@router.get("/posts")
async def list_posts(
    ctx: Context,
    auth: Authenticated,
    query: str | None = None,
    campaign_id: Annotated[int | None, Query(gt=0)] = None,
    published_from: str | None = None,
    published_to: str | None = None,
    sort: str | None = None,
    order: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
    cursor: str | None = None,
) -> JSONResponse:
    """公開済み投稿を、絞り込み・意味検索・並び替え付きで返す。"""
    view = await PostService(ctx).list(
        auth,
        query=query,
        campaign_id=campaign_id,
        published_from=parse_query_datetime(published_from, "published_from"),
        published_to=parse_query_datetime(published_to, "published_to"),
        sort=sort,
        order=order,
        limit=limit,
        cursor=cursor,
    )
    return ok(serialize_post_list(view))


@router.get("/posts/{post_id}")
async def get_post(
    post_id: Annotated[int, Path(gt=0)], ctx: Context, auth: Authenticated
) -> JSONResponse:
    """公開済み投稿の本文・施策・UTM・計測結果を返す。"""
    return ok(serialize_post_detail(await PostService(ctx).detail(auth, post_id)))


@router.get("/metrics")
async def get_metrics(
    ctx: Context,
    auth: Authenticated,
    published_from: str | None = None,
    published_to: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
    cursor: str | None = None,
) -> JSONResponse:
    """全体のサマリーと、施策ごとの計測結果を集計して返す。"""
    view = await MetricsService(ctx).report(
        auth,
        published_from=parse_query_datetime(published_from, "published_from"),
        published_to=parse_query_datetime(published_to, "published_to"),
        limit=limit,
        cursor=cursor,
    )
    return ok(serialize_metrics_report(view))
