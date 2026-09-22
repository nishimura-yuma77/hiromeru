"""計測結果の集計（API_DESIGN 6.6）。"""

import uuid
from datetime import datetime
from typing import Any, cast

from sqlalchemy import text

from core.errors import AppError
from domain.constants import LIST_SNAPSHOT_CLEANUP_LIMIT
from domain.metrics import EMPTY_SUMMARY, MetricsSummary
from domain.timefmt import format_utc, parse_aware_datetime
from repositories.campaigns import CampaignRepository
from repositories.posts import PostRepository
from repositories.snapshots import SnapshotRepository
from services.context import AuthContext, ServiceContext
from services.paging import validate_range
from services.snapshot_paging import (
    SnapshotCursor,
    issue_snapshot_cursor,
    read_snapshot_cursor,
    snapshot_filter_hash,
)
from services.views import CampaignMetricsView, MetricsReportView

_RESOURCE = "metrics"


def _total(summaries: list[MetricsSummary]) -> MetricsSummary:
    if not summaries:
        return EMPTY_SUMMARY
    return MetricsSummary(
        sum(s.post_count for s in summaries),
        sum(s.completed_count for s in summaries),
        sum(s.pending_count for s in summaries),
        sum(s.failed_count for s in summaries),
        sum(s.x_pv_count for s in summaries),
        sum(s.landing_user_count for s in summaries),
    )


def _summary_projection(summary: MetricsSummary) -> dict[str, Any]:
    """集計値をSnapshot用JSONへ固定する。"""
    return {
        "post_count": summary.post_count,
        "completed_count": summary.completed_count,
        "pending_count": summary.pending_count,
        "failed_count": summary.failed_count,
        "x_pv_count": summary.x_pv_count,
        "landing_user_count": summary.landing_user_count,
    }


def _projection_summary(value: dict[str, Any]) -> MetricsSummary:
    """SnapshotのJSONから集計値を戻す。"""
    return MetricsSummary(
        cast(int, value["post_count"]),
        cast(int, value["completed_count"]),
        cast(int, value["pending_count"]),
        cast(int, value["failed_count"]),
        cast(int, value["x_pv_count"]),
        cast(int, value["landing_user_count"]),
    )


def _campaign_projection(item: CampaignMetricsView) -> dict[str, Any]:
    """Campaign集計の表示値をSnapshot用JSONへ固定する。"""
    return {
        "id": item.id,
        "title": item.title,
        "archived_at": format_utc(item.archived_at) if item.archived_at is not None else None,
        "summary": _summary_projection(item.summary),
    }


def _projection_campaign(value: dict[str, Any]) -> CampaignMetricsView:
    """SnapshotのJSONからCampaign集計を戻す。"""
    archived_at = value["archived_at"]
    return CampaignMetricsView(
        id=cast(int, value["id"]),
        title=cast(str, value["title"]),
        archived_at=(
            parse_aware_datetime(cast(str, archived_at)) if archived_at is not None else None
        ),
        summary=_projection_summary(cast(dict[str, Any], value["summary"])),
    )


class MetricsService:
    """全体のサマリーと、施策ごとの集計。"""

    def __init__(self, ctx: ServiceContext) -> None:
        """サービスの依存を受け取る。"""
        self._ctx = ctx

    async def report(
        self,
        auth: AuthContext,
        *,
        published_from: datetime | None,
        published_to: datetime | None,
        limit: int,
        cursor: str | None,
    ) -> MetricsReportView:
        """期間全体の固定Summaryと、CampaignのSnapshot Pageを返す。

        Raises:
            AppError: 期間またはcursorが不正な場合（INVALID_ARGUMENT）。
        """
        validate_range(published_from, published_to, "published_from・published_to")
        filter_hash = self._filter_hash(published_from, published_to)
        if cursor is not None:
            parsed_cursor = read_snapshot_cursor(
                self._ctx.settings.auth_secret(), _RESOURCE, cursor
            )
            if parsed_cursor.filter_hash != filter_hash:
                raise AppError("INVALID_ARGUMENT", "cursor と一覧条件が一致しません。")
            return await self._snapshot_page(
                auth,
                parsed_cursor,
                published_from,
                published_to,
                filter_hash,
                limit,
            )
        return await self._first_page(
            auth, published_from, published_to, filter_hash, limit
        )

    async def _first_page(
        self,
        auth: AuthContext,
        published_from: datetime | None,
        published_to: datetime | None,
        filter_hash: str,
        limit: int,
    ) -> MetricsReportView:
        """Repeatable Read内で全期間Summaryと全Campaign Projectionを固定する。"""
        now = self._ctx.clock.now()
        snapshot_id = self._ctx.new_uuid()
        async with self._ctx.session_factory() as session, session.begin():
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
            snapshots = SnapshotRepository(session)
            await snapshots.cleanup_expired(now, LIST_SNAPSHOT_CLEANUP_LIMIT)
            summaries = await PostRepository(session).summarize(
                auth.company_id,
                published_from=published_from,
                published_to=published_to,
            )
            references = await CampaignRepository(session).references(
                auth.company_id, list(summaries)
            )
            campaigns = sorted(
                (
                    CampaignMetricsView(cid, *references.get(cid, ("", None)), summary)
                    for cid, summary in summaries.items()
                ),
                key=lambda view: (view.summary.x_pv_count, view.id),
                reverse=True,
            )
            summary = _total(list(summaries.values()))
            projections = [_campaign_projection(item) for item in campaigns]
            await snapshots.create(
                snapshot_id=snapshot_id,
                marketer_id=auth.marketer_id,
                resource=_RESOURCE,
                filter_hash=filter_hash,
                items=projections,
                now=now,
                summary=_summary_projection(summary),
            )
        shown = projections[:limit]
        next_cursor = (
            self._next_cursor(snapshot_id, limit, filter_hash)
            if len(projections) > limit
            else None
        )
        return MetricsReportView(
            published_from,
            published_to,
            summary,
            [_projection_campaign(item) for item in shown],
            next_cursor,
        )

    async def _snapshot_page(
        self,
        auth: AuthContext,
        cursor: SnapshotCursor,
        published_from: datetime | None,
        published_to: datetime | None,
        filter_hash: str,
        limit: int,
    ) -> MetricsReportView:
        """元テーブルを再集計せず、固定SummaryとCampaign Sliceだけを返す。"""
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
        if snapshot_page is None or snapshot_page.summary is None:
            raise AppError("INVALID_ARGUMENT", "cursor が正しくありません。")
        items = snapshot_page.items
        shown = items[:limit]
        next_position = cursor.position + limit
        next_cursor = (
            self._next_cursor(cursor.snapshot_id, next_position, filter_hash)
            if len(items) > limit
            else None
        )
        return MetricsReportView(
            published_from,
            published_to,
            _projection_summary(snapshot_page.summary),
            [_projection_campaign(item) for item in shown],
            next_cursor,
        )

    def _next_cursor(self, snapshot_id: uuid.UUID, position: int, filter_hash: str) -> str:
        return issue_snapshot_cursor(
            self._ctx.settings.auth_secret(),
            _RESOURCE,
            snapshot_id,
            position,
            filter_hash,
        )

    @staticmethod
    def _filter_hash(published_from: datetime | None, published_to: datetime | None) -> str:
        """日時表現をUTCへ正規化した期間条件Hashを返す。"""
        return snapshot_filter_hash(
            {
                "published_from": format_utc(published_from)
                if published_from is not None
                else None,
                "published_to": format_utc(published_to) if published_to is not None else None,
            }
        )
