"""サービスが返す読み取り用の値（JSON化はAPI層が行う）。"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from domain.metrics import MetricsSummary


@dataclass(frozen=True)
class MetricsView:
    """投稿ごとの計測結果。`completed` 以外では値は None。"""

    status: str
    scheduled_at: datetime
    measured_at: datetime | None
    x_pv_count: int | None
    landing_user_count: int | None


@dataclass(frozen=True)
class SessionView:
    """Sessionの表示情報。"""

    session_id: int
    title: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class SessionListView:
    """Session一覧。"""

    sessions: list[SessionView]
    next_cursor: str | None


@dataclass(frozen=True)
class TurnErrorView:
    """failed・blocked のTurnのエラー。"""

    code: str
    message: str
    retryable: bool


@dataclass(frozen=True)
class SecurityNoticeView:
    """セキュリティ通知。種別・制御内容・検出日時だけを返す。"""

    event_type: str
    enforcement: str
    detected_at: datetime


@dataclass(frozen=True)
class TurnItemView:
    """Turnに含める表示対象のItem。"""

    item_id: int
    item_number: int
    type: str
    content: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True)
class TurnView:
    """5.1のTurn。"""

    agent_turn_id: int
    turn_number: int
    kind: str
    status: str
    error: TurnErrorView | None
    started_at: datetime | None
    completed_at: datetime | None
    security_notices: list[SecurityNoticeView] = field(default_factory=list)
    items: list[TurnItemView] = field(default_factory=list)


@dataclass(frozen=True)
class HistoryView:
    """Session履歴。"""

    session: SessionView
    turns: list[TurnView]
    has_more: bool


@dataclass(frozen=True)
class CampaignListItemView:
    """施策一覧の1件。"""

    id: int
    title: str
    objective: str
    created_at: datetime
    updated_at: datetime
    similarity: float | None
    metrics_summary: MetricsSummary


@dataclass(frozen=True)
class CampaignListView:
    """施策一覧。"""

    campaigns: list[CampaignListItemView]
    next_cursor: str | None


@dataclass(frozen=True)
class CampaignView:
    """施策の全項目。"""

    id: int
    title: str
    target_profile: str
    background: str
    objective: str
    plan: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class CampaignPostView:
    """施策詳細に含める投稿。"""

    post_id: int
    body: str
    published_at: datetime
    metrics: MetricsView


@dataclass(frozen=True)
class MemoryBriefView:
    """施策詳細に含める記憶。"""

    id: int
    content: str


@dataclass(frozen=True)
class CampaignDetailView:
    """施策詳細。"""

    campaign: CampaignView
    metrics_summary: MetricsSummary
    posts: list[CampaignPostView]
    has_more_posts: bool
    memories: list[MemoryBriefView]
    has_more_memories: bool


@dataclass(frozen=True)
class CampaignEditView:
    """施策編集の結果。"""

    id: int
    title: str
    updated_at: datetime


@dataclass(frozen=True)
class PostListItemView:
    """投稿一覧の1件。"""

    post_id: int
    campaign_id: int
    campaign_title: str
    body: str
    x_post_id: str
    published_at: datetime
    similarity: float | None
    metrics: MetricsView


@dataclass(frozen=True)
class PostListView:
    """投稿一覧。"""

    posts: list[PostListItemView]
    next_cursor: str | None


@dataclass(frozen=True)
class TrackingView:
    """投稿のトラッキング情報。"""

    landing_url: str
    utm_source: str
    utm_medium: str
    utm_campaign: str
    utm_content: str
    tracked_url: str


@dataclass(frozen=True)
class PostDetailView:
    """投稿詳細。"""

    post_id: int
    body: str
    x_post_id: str
    published_at: datetime
    campaign_id: int
    campaign_title: str
    tracking: TrackingView
    metrics: MetricsView


@dataclass(frozen=True)
class CampaignMetricsView:
    """施策ごとの計測集計。"""

    id: int
    title: str
    summary: MetricsSummary


@dataclass(frozen=True)
class MetricsReportView:
    """計測結果集計。"""

    published_from: datetime | None
    published_to: datetime | None
    summary: MetricsSummary
    campaigns: list[CampaignMetricsView]


@dataclass(frozen=True)
class MemoryView:
    """記憶一覧の1件。"""

    id: int
    content: str
    similarity: float | None
    campaigns: list[tuple[int, str]]
    posts: list[tuple[int, datetime]]


@dataclass(frozen=True)
class MemoryListView:
    """記憶一覧。"""

    memories: list[MemoryView]
    next_cursor: str | None
