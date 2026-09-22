"""計測結果の集計（API_DESIGN 6.6）。"""

from datetime import datetime

from domain.metrics import EMPTY_SUMMARY, MetricsSummary
from repositories.campaigns import CampaignRepository
from repositories.posts import PostRepository
from services.context import AuthContext, ServiceContext
from services.paging import validate_range
from services.views import CampaignMetricsView, MetricsReportView


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
    ) -> MetricsReportView:
        """期間内の公開済み投稿を集計する。投稿がなくても空の集計を返す。

        Raises:
            AppError: 期間の指定が不正な場合（INVALID_ARGUMENT）。
        """
        validate_range(published_from, published_to, "published_from・published_to")
        async with self._ctx.session_factory() as session:
            summaries = await PostRepository(session).summarize(
                auth.company_id, published_from=published_from, published_to=published_to
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
        return MetricsReportView(
            published_from, published_to, _total(list(summaries.values())), campaigns
        )
