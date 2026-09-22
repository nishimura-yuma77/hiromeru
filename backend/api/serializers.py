"""サービスの値をResponseのJSONへ変換する（API_DESIGN 5章〜7章）。日時はUTCのISO 8601。"""

from typing import Any

from domain.metrics import MetricsSummary
from domain.timefmt import format_utc
from services.views import (
    CampaignDetailView,
    CampaignEditView,
    CampaignListView,
    HistoryView,
    MemoryCampaignListView,
    MemoryListView,
    MemoryPostListView,
    MetricsReportView,
    MetricsView,
    PostDetailView,
    PostListView,
    SessionListView,
    SessionView,
    TurnView,
)


def _iso(value: Any) -> str | None:  # noqa: ANN401 - datetime | None
    return None if value is None else format_utc(value)


def serialize_summary(summary: MetricsSummary) -> dict[str, Any]:
    """`metrics_summary` の形式。"""
    return {
        "post_count": summary.post_count,
        "completed_count": summary.completed_count,
        "pending_count": summary.pending_count,
        "failed_count": summary.failed_count,
        "x_pv_count": summary.x_pv_count,
        "landing_user_count": summary.landing_user_count,
        "landing_rate": summary.landing_rate,
    }


def serialize_metrics(metrics: MetricsView) -> dict[str, Any]:
    """投稿ごとの `metrics` の形式。"""
    return {
        "status": metrics.status,
        "scheduled_at": _iso(metrics.scheduled_at),
        "measured_at": _iso(metrics.measured_at),
        "x_pv_count": metrics.x_pv_count,
        "landing_user_count": metrics.landing_user_count,
    }


def serialize_session(view: SessionView) -> dict[str, Any]:
    """Sessionの形式。"""
    return {
        "session_id": view.session_id,
        "title": view.title,
        "created_at": _iso(view.created_at),
        "updated_at": _iso(view.updated_at),
    }


def serialize_session_list(view: SessionListView) -> dict[str, Any]:
    """Session一覧の形式。"""
    return {
        "sessions": [serialize_session(item) for item in view.sessions],
        "next_cursor": view.next_cursor,
    }


def serialize_turn(view: TurnView) -> dict[str, Any]:
    """5.1のTurnの形式。"""
    return {
        "agent_turn_id": view.agent_turn_id,
        "turn_number": view.turn_number,
        "kind": view.kind,
        "status": view.status,
        "error": None
        if view.error is None
        else {
            "code": view.error.code,
            "message": view.error.message,
            "retryable": view.error.retryable,
        },
        "approval_state": None
        if view.approval_state is None
        else {
            "operation": view.approval_state.operation,
            "status": view.approval_state.status,
            "external_effect_started": view.approval_state.external_effect_started,
            "external_succeeded": view.approval_state.external_succeeded,
            "recovery": view.approval_state.recovery,
        },
        "started_at": _iso(view.started_at),
        "completed_at": _iso(view.completed_at),
        "security_notices": [
            {
                "event_type": notice.event_type,
                "enforcement": notice.enforcement,
                "detected_at": _iso(notice.detected_at),
            }
            for notice in view.security_notices
        ],
        "items": [
            {
                "item_id": item.item_id,
                "item_number": item.item_number,
                "type": item.type,
                "content": item.content,
                "created_at": _iso(item.created_at),
            }
            for item in view.items
        ],
    }


def serialize_history(view: HistoryView) -> dict[str, Any]:
    """Session履歴の形式。"""
    return {
        "session": serialize_session(view.session),
        "turns": [serialize_turn(turn) for turn in view.turns],
        "has_more": view.has_more,
    }


def serialize_campaign_list(view: CampaignListView) -> dict[str, Any]:
    """施策一覧の形式。"""
    return {
        "campaigns": [
            {
                "id": item.id,
                "title": item.title,
                "objective": item.objective,
                "created_at": _iso(item.created_at),
                "updated_at": _iso(item.updated_at),
                "archived_at": _iso(item.archived_at),
                "similarity": item.similarity,
                "metrics_summary": serialize_summary(item.metrics_summary),
            }
            for item in view.campaigns
        ],
        "next_cursor": view.next_cursor,
    }


def serialize_campaign_detail(view: CampaignDetailView) -> dict[str, Any]:
    """施策詳細の形式。"""
    campaign = view.campaign
    return {
        "campaign": {
            "id": campaign.id,
            "title": campaign.title,
            "target_profile": campaign.target_profile,
            "background": campaign.background,
            "objective": campaign.objective,
            "plan": campaign.plan,
            "created_at": _iso(campaign.created_at),
            "updated_at": _iso(campaign.updated_at),
            "archived_at": _iso(campaign.archived_at),
        },
        "metrics_summary": serialize_summary(view.metrics_summary),
        "posts": [
            {
                "post_id": post.post_id,
                "body": post.body,
                "published_at": _iso(post.published_at),
                "metrics": serialize_metrics(post.metrics),
            }
            for post in view.posts
        ],
        "has_more_posts": view.has_more_posts,
        "memories": [{"id": memory.id, "content": memory.content} for memory in view.memories],
        "has_more_memories": view.has_more_memories,
    }


def serialize_campaign_edit(view: CampaignEditView) -> dict[str, Any]:
    """施策編集の結果の形式（`agent_turn_id` は返さない）。"""
    return {"id": view.id, "title": view.title, "updated_at": _iso(view.updated_at)}


def serialize_post_list(view: PostListView) -> dict[str, Any]:
    """投稿一覧の形式。"""
    return {
        "posts": [
            {
                "post_id": item.post_id,
                "campaign_id": item.campaign_id,
                "campaign_title": item.campaign_title,
                "campaign_archived_at": _iso(item.campaign_archived_at),
                "body": item.body,
                "x_post_id": item.x_post_id,
                "published_at": _iso(item.published_at),
                "similarity": item.similarity,
                "metrics": serialize_metrics(item.metrics),
            }
            for item in view.posts
        ],
        "next_cursor": view.next_cursor,
    }


def serialize_post_detail(view: PostDetailView) -> dict[str, Any]:
    """投稿詳細の形式。"""
    tracking = view.tracking
    return {
        "post": {
            "post_id": view.post_id,
            "body": view.body,
            "x_post_id": view.x_post_id,
            "published_at": _iso(view.published_at),
        },
        "campaign": {
            "id": view.campaign_id,
            "title": view.campaign_title,
            "archived_at": _iso(view.campaign_archived_at),
        },
        "tracking": {
            "landing_url": tracking.landing_url,
            "utm_source": tracking.utm_source,
            "utm_medium": tracking.utm_medium,
            "utm_campaign": tracking.utm_campaign,
            "utm_content": tracking.utm_content,
            "tracked_url": tracking.tracked_url,
        },
        "metrics": serialize_metrics(view.metrics),
    }


def serialize_metrics_report(view: MetricsReportView) -> dict[str, Any]:
    """計測結果集計の形式。"""
    return {
        "published_from": _iso(view.published_from),
        "published_to": _iso(view.published_to),
        "summary": serialize_summary(view.summary),
        "campaigns": [
            {
                "id": item.id,
                "title": item.title,
                "archived_at": _iso(item.archived_at),
                **serialize_summary(item.summary),
            }
            for item in view.campaigns
        ],
        "next_cursor": view.next_cursor,
    }


def serialize_memory_list(view: MemoryListView) -> dict[str, Any]:
    """記憶一覧の形式。"""
    return {
        "memories": [
            {
                "id": memory.id,
                "content": memory.content,
                "similarity": memory.similarity,
                "campaigns": [
                    {"id": cid, "title": title, "archived_at": _iso(archived_at)}
                    for cid, title, archived_at in memory.campaigns
                ],
                "campaigns_next_cursor": memory.campaigns_next_cursor,
                "posts": [
                    {"post_id": pid, "published_at": _iso(published_at)}
                    for pid, published_at in memory.posts
                ],
                "posts_next_cursor": memory.posts_next_cursor,
            }
            for memory in view.memories
        ],
        "next_cursor": view.next_cursor,
    }


def serialize_memory_campaigns(view: MemoryCampaignListView) -> dict[str, Any]:
    """記憶に関連する施策一覧の形式。"""
    return {
        "campaigns": [
            {"id": cid, "title": title, "archived_at": _iso(archived_at)}
            for cid, title, archived_at in view.campaigns
        ],
        "next_cursor": view.next_cursor,
    }


def serialize_memory_posts(view: MemoryPostListView) -> dict[str, Any]:
    """記憶に関連する公開済み投稿一覧の形式。"""
    return {
        "posts": [
            {"post_id": post_id, "published_at": _iso(published_at)}
            for post_id, published_at in view.posts
        ],
        "next_cursor": view.next_cursor,
    }
