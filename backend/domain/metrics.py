"""計測結果の集計（API_DESIGN 6.1「計測結果の表現」）。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class MetricsSummary:
    """投稿の集まりの計測集計。"""

    post_count: int
    completed_count: int
    pending_count: int
    failed_count: int
    x_pv_count: int
    landing_user_count: int

    @property
    def landing_rate(self) -> float | None:
        """流入率（遷移ユーザー数 ÷ PV数）。PV数が0の場合は None。丸めない。"""
        if self.x_pv_count == 0:
            return None
        return self.landing_user_count / self.x_pv_count


EMPTY_SUMMARY = MetricsSummary(0, 0, 0, 0, 0, 0)
