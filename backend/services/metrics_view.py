"""計測結果の表示用変換。"""

from domain.enums import PostMetricStatus
from models import PostMetric
from services.views import MetricsView


def to_metrics_view(metric: PostMetric) -> MetricsView:
    """`completed` のときだけ値を持つ計測結果へ変換する（API_DESIGN 6.1）。"""
    completed = metric.status == PostMetricStatus.COMPLETED
    return MetricsView(
        status=metric.status.value,
        scheduled_at=metric.scheduled_at,
        measured_at=metric.measured_at if completed else None,
        x_pv_count=metric.x_pv_count if completed else None,
        landing_user_count=metric.landing_user_count if completed else None,
    )
