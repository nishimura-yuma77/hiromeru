"""公開済み投稿の参照（API_DESIGN 6.4、6.5）。"""

from datetime import datetime
from typing import Any, Literal, cast

from core.errors import AppError
from domain.cursor import CursorValue, encode_cursor
from domain.timefmt import format_utc
from repositories.campaigns import CampaignRepository
from repositories.posts import PostFilter, PostPage, PostRepository, PostRow
from services.context import AuthContext, ServiceContext
from services.metrics_view import to_metrics_view
from services.paging import (
    normalize_query,
    read_cursor,
    require_datetime,
    require_int,
    validate_range,
)
from services.views import PostDetailView, PostListItemView, PostListView, TrackingView

_CURSOR_KIND = "posts"
_Sort = Literal["published_at", "x_pv_count"]
_Order = Literal["asc", "desc"]
_SORTS = ("published_at", "x_pv_count")
_ORDERS = ("asc", "desc")


def _to_item(row: PostRow) -> PostListItemView:
    post = row.post
    return PostListItemView(
        post.id,
        post.campaign_id,
        row.campaign_title,
        post.body,
        post.x_post_id,
        post.published_at,
        row.similarity,
        to_metrics_view(row.metric),
    )


class PostService:
    """公開済み投稿の一覧・詳細。"""

    def __init__(self, ctx: ServiceContext) -> None:
        """サービスの依存を受け取る。"""
        self._ctx = ctx

    async def list(
        self,
        auth: AuthContext,
        *,
        query: str | None,
        campaign_id: int | None,
        published_from: datetime | None,
        published_to: datetime | None,
        sort: str | None,
        order: str | None,
        limit: int,
        cursor: str | None,
    ) -> PostListView:
        """公開済み投稿を、絞り込み・意味検索・並び替え付きで返す（6.4）。

        Raises:
            AppError: 条件・組み合わせの不正（INVALID_ARGUMENT）、施策なし（CAMPAIGN_NOT_FOUND）。
        """
        search = normalize_query(query)
        if search is not None and (cursor is not None or sort is not None or order is not None):
            raise AppError(
                "INVALID_ARGUMENT", "query は cursor・sort・order と同時に指定できません。"
            )
        if (sort is not None and sort not in _SORTS) or (
            order is not None and order not in _ORDERS
        ):
            raise AppError("INVALID_ARGUMENT", "sort または order が正しくありません。")
        validate_range(published_from, published_to, "published_from・published_to")
        page = self._page(sort, order, cursor)
        flt = PostFilter(campaign_id, published_from, published_to)
        vector = await self._ctx.embedding.embed(search) if search is not None else None
        async with self._ctx.session_factory() as session:
            # 存在しない・別会社の施策は、空の一覧ではなく404とする。
            if (
                campaign_id is not None
                and await CampaignRepository(session).get(auth.company_id, campaign_id) is None
            ):
                raise AppError("CAMPAIGN_NOT_FOUND")
            repository = PostRepository(session)
            if vector is not None:
                rows = await repository.search_posts(auth.company_id, vector, flt, limit)
                return PostListView([_to_item(row) for row in rows], None)
            rows = await repository.list_posts(auth.company_id, flt, page, limit + 1)
        shown = rows[:limit]
        next_cursor = self._next_cursor(page, shown[-1]) if len(rows) > limit else None
        return PostListView([_to_item(row) for row in shown], next_cursor)

    @staticmethod
    def _page(sort: str | None, order: str | None, cursor: str | None) -> PostPage:
        """並び順とカーソルを確定する。cursor と異なる sort・order の指定は不正とする。"""
        if cursor is None:
            return PostPage(cast(_Sort, sort or "published_at"), cast(_Order, order or "desc"))
        values = read_cursor(cursor, _CURSOR_KIND)
        cursor_sort, cursor_order = values.get("sort"), values.get("order")
        if cursor_sort not in _SORTS or cursor_order not in _ORDERS:
            raise AppError("INVALID_ARGUMENT", "cursor が正しくありません。")
        if sort not in (None, cursor_sort) or order not in (None, cursor_order):
            raise AppError("INVALID_ARGUMENT", "cursor と異なる sort・order は指定できません。")
        parsed: dict[str, Any] = {
            "id": require_int(values, "id"),
            "published_at": require_datetime(values, "published_at"),
        }
        if cursor_sort == "x_pv_count":
            parsed["is_null"] = bool(require_int(values, "is_null"))
            if not parsed["is_null"]:
                parsed["x_pv_count"] = require_int(values, "x_pv_count")
        return PostPage(cast(_Sort, cursor_sort), cast(_Order, cursor_order), parsed)

    @staticmethod
    def _next_cursor(page: PostPage, last: PostRow) -> str:
        values: dict[str, CursorValue] = {
            "sort": page.sort,
            "order": page.order,
            "id": last.post.id,
            "published_at": format_utc(last.post.published_at),
        }
        if page.sort == "x_pv_count":
            values["is_null"] = int(last.metric.x_pv_count is None)
            values["x_pv_count"] = last.metric.x_pv_count
        return encode_cursor(_CURSOR_KIND, values)

    async def detail(self, auth: AuthContext, post_id: int) -> PostDetailView:
        """公開済み投稿の本文・施策・UTM・計測結果を返す（6.5）。

        Raises:
            AppError: 存在しない、別会社、公開済みでない場合（POST_NOT_FOUND）。
        """
        async with self._ctx.session_factory() as session:
            repository = PostRepository(session)
            row = await repository.get_published(auth.company_id, post_id)
            tracking = await repository.get_tracking(post_id) if row is not None else None
        if row is None or tracking is None:
            raise AppError("POST_NOT_FOUND")
        post = row.post
        return PostDetailView(
            post_id=post.id,
            body=post.body,
            x_post_id=post.x_post_id,
            published_at=post.published_at,
            campaign_id=post.campaign_id,
            campaign_title=row.campaign_title,
            tracking=TrackingView(
                tracking.landing_url,
                tracking.utm_source,
                tracking.utm_medium,
                tracking.utm_campaign,
                tracking.utm_content,
                tracking.tracked_url,
            ),
            metrics=to_metrics_view(row.metric),
        )
