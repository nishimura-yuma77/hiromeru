"""公開済み投稿の参照（API_DESIGN 6.4、6.5）。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal, cast

from sqlalchemy import text

from core.errors import AppError
from domain.constants import LIST_SNAPSHOT_CLEANUP_LIMIT
from domain.timefmt import format_utc, parse_aware_datetime
from repositories.campaigns import CampaignRepository
from repositories.posts import PostFilter, PostPage, PostRepository, PostRow
from repositories.snapshots import SnapshotRepository
from services.context import AuthContext, ServiceContext
from services.metrics_view import to_metrics_view
from services.paging import (
    normalize_query,
    validate_range,
)
from services.snapshot_paging import (
    SnapshotCursor,
    issue_snapshot_cursor,
    read_snapshot_cursor,
    snapshot_filter_hash,
)
from services.views import MetricsView, PostDetailView, PostListItemView, PostListView, TrackingView

_Sort = Literal["published_at", "x_pv_count"]
_Order = Literal["asc", "desc"]
_SORTS = ("published_at", "x_pv_count")
_ORDERS = ("asc", "desc")
_RESOURCE = "posts"


def _to_item(row: PostRow) -> PostListItemView:
    post = row.post
    return PostListItemView(
        post.id,
        post.campaign_id,
        row.campaign_title,
        row.campaign_archived_at,
        post.body,
        post.x_post_id,
        post.published_at,
        row.similarity,
        to_metrics_view(row.metric),
    )


def _item_projection(item: PostListItemView) -> dict[str, Any]:
    """投稿一覧の表示値をSnapshot用JSONへ固定する。"""
    metrics = item.metrics
    return {
        "post_id": item.post_id,
        "campaign_id": item.campaign_id,
        "campaign_title": item.campaign_title,
        "campaign_archived_at": (
            format_utc(item.campaign_archived_at) if item.campaign_archived_at is not None else None
        ),
        "body": item.body,
        "x_post_id": item.x_post_id,
        "published_at": format_utc(item.published_at),
        "similarity": item.similarity,
        "metrics": {
            "status": metrics.status,
            "scheduled_at": format_utc(metrics.scheduled_at),
            "measured_at": format_utc(metrics.measured_at)
            if metrics.measured_at is not None
            else None,
            "x_pv_count": metrics.x_pv_count,
            "landing_user_count": metrics.landing_user_count,
        },
    }


def _projection_item(value: dict[str, Any]) -> PostListItemView:
    """DBに保存した固定Projectionを表示値へ戻す。"""
    metrics = cast(dict[str, Any], value["metrics"])
    archived_at = value["campaign_archived_at"]
    measured_at = metrics["measured_at"]
    return PostListItemView(
        post_id=cast(int, value["post_id"]),
        campaign_id=cast(int, value["campaign_id"]),
        campaign_title=cast(str, value["campaign_title"]),
        campaign_archived_at=(
            parse_aware_datetime(cast(str, archived_at)) if archived_at is not None else None
        ),
        body=cast(str, value["body"]),
        x_post_id=cast(str, value["x_post_id"]),
        published_at=parse_aware_datetime(cast(str, value["published_at"])),
        similarity=cast(float | None, value["similarity"]),
        metrics=MetricsView(
            status=cast(str, metrics["status"]),
            scheduled_at=parse_aware_datetime(cast(str, metrics["scheduled_at"])),
            measured_at=(
                parse_aware_datetime(cast(str, measured_at)) if measured_at is not None else None
            ),
            x_pv_count=cast(int | None, metrics["x_pv_count"]),
            landing_user_count=cast(int | None, metrics["landing_user_count"]),
        ),
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
        flt = PostFilter(campaign_id, published_from, published_to)
        vector = await self._ctx.embedding.embed(search) if search is not None else None
        if vector is not None:
            return await self._search(auth, flt, campaign_id, vector, limit)

        parsed_cursor = (
            read_snapshot_cursor(self._ctx.settings.auth_secret(), _RESOURCE, cursor)
            if cursor is not None
            else None
        )
        page = self._page(sort, order, parsed_cursor)
        filter_hash = self._filter_hash(flt, page)
        if parsed_cursor is not None:
            if parsed_cursor.filter_hash != filter_hash:
                raise AppError("INVALID_ARGUMENT", "cursor と一覧条件が一致しません。")
            return await self._snapshot_page(auth, parsed_cursor, filter_hash, limit)
        return await self._first_page(auth, flt, page, campaign_id, filter_hash, limit)

    async def _search(
        self,
        auth: AuthContext,
        flt: PostFilter,
        campaign_id: int | None,
        vector: list[float],
        limit: int,
    ) -> PostListView:
        """意味検索はLive Queryの1 Pageだけを返し、Snapshotを作らない。"""
        async with self._ctx.session_factory() as session:
            if (
                campaign_id is not None
                and await CampaignRepository(session).get(auth.company_id, campaign_id) is None
            ):
                raise AppError("CAMPAIGN_NOT_FOUND")
            rows = await PostRepository(session).search_posts(auth.company_id, vector, flt, limit)
        return PostListView([_to_item(row) for row in rows], None)

    async def _first_page(
        self,
        auth: AuthContext,
        flt: PostFilter,
        page: PostPage,
        campaign_id: int | None,
        filter_hash: str,
        limit: int,
    ) -> PostListView:
        """Repeatable Read内で全Projectionを固定し、先頭Pageを返す。"""
        now = self._ctx.clock.now()
        snapshot_id = self._ctx.new_uuid()
        async with self._ctx.session_factory() as session, session.begin():
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
            snapshots = SnapshotRepository(session)
            await snapshots.cleanup_expired(now, LIST_SNAPSHOT_CLEANUP_LIMIT)
            if (
                campaign_id is not None
                and await CampaignRepository(session).get(auth.company_id, campaign_id) is None
            ):
                raise AppError("CAMPAIGN_NOT_FOUND")
            rows = await PostRepository(session).list_posts(auth.company_id, flt, page)
            projections = [_item_projection(_to_item(row)) for row in rows]
            await snapshots.create(
                snapshot_id=snapshot_id,
                marketer_id=auth.marketer_id,
                resource=_RESOURCE,
                filter_hash=filter_hash,
                items=projections,
                now=now,
            )
        shown = projections[:limit]
        next_cursor = (
            self._next_cursor(snapshot_id, limit, filter_hash, page)
            if len(projections) > limit
            else None
        )
        return PostListView([_projection_item(item) for item in shown], next_cursor)

    async def _snapshot_page(
        self,
        auth: AuthContext,
        cursor: SnapshotCursor,
        filter_hash: str,
        limit: int,
    ) -> PostListView:
        """元テーブルを参照せず、固定済みSnapshotの続きだけを返す。"""
        async with self._ctx.session_factory() as session:
            snapshot_page = await SnapshotRepository(session).read_page(
                snapshot_id=cursor.snapshot_id,
                marketer_id=auth.marketer_id,
                resource=_RESOURCE,
                filter_hash=filter_hash,
                now=self._ctx.clock.now(),
                position=cursor.position,
                limit=limit,
            )
        if snapshot_page is None:
            raise AppError("INVALID_ARGUMENT", "cursor が正しくありません。")
        items = snapshot_page.items
        shown = items[:limit]
        next_position = cursor.position + limit
        next_cursor = (
            self._next_cursor(
                cursor.snapshot_id,
                next_position,
                filter_hash,
                PostPage(cast(_Sort, cursor.sort), cast(_Order, cursor.order)),
            )
            if len(items) > limit
            else None
        )
        return PostListView([_projection_item(item) for item in shown], next_cursor)

    @staticmethod
    def _page(sort: str | None, order: str | None, cursor: SnapshotCursor | None) -> PostPage:
        """並び順とカーソルを確定する。cursor と異なる sort・order の指定は不正とする。"""
        if cursor is None:
            return PostPage(cast(_Sort, sort or "published_at"), cast(_Order, order or "desc"))
        cursor_sort, cursor_order = cursor.sort, cursor.order
        if cursor_sort not in _SORTS or cursor_order not in _ORDERS:
            raise AppError("INVALID_ARGUMENT", "cursor が正しくありません。")
        if sort not in (None, cursor_sort) or order not in (None, cursor_order):
            raise AppError("INVALID_ARGUMENT", "cursor と異なる sort・order は指定できません。")
        return PostPage(cast(_Sort, cursor_sort), cast(_Order, cursor_order))

    def _next_cursor(
        self,
        snapshot_id: uuid.UUID,
        position: int,
        filter_hash: str,
        page: PostPage,
    ) -> str:
        return issue_snapshot_cursor(
            self._ctx.settings.auth_secret(),
            _RESOURCE,
            snapshot_id,
            position,
            filter_hash,
            page.sort,
            page.order,
        )

    @staticmethod
    def _filter_hash(flt: PostFilter, page: PostPage) -> str:
        """省略値と日時表現を正規化した条件Hashを返す。"""
        return snapshot_filter_hash(
            {
                "campaign_id": flt.campaign_id,
                "published_from": (
                    format_utc(flt.published_from) if flt.published_from is not None else None
                ),
                "published_to": format_utc(flt.published_to)
                if flt.published_to is not None
                else None,
                "sort": page.sort,
                "order": page.order,
            }
        )

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
            campaign_archived_at=row.campaign_archived_at,
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
