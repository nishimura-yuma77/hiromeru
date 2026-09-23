"""投稿Metrics CronのClaim、Lease、Fencing付き状態遷移。"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from domain.cron import retry_delay
from domain.enums import PostMetricStatus
from models import Post, PostMetric, PostTrackingLink


@dataclass(frozen=True)
class MetricClaim:
    """Transaction外でProviderを呼ぶためのClaim Snapshot。"""

    post_id: int
    token: uuid.UUID
    attempt_count: int
    scheduled_at: datetime
    published_at: datetime
    x_post_id: str
    utm_source: str
    utm_medium: str
    utm_campaign: str
    utm_content: str
    x_pv_count: int | None
    landing_user_count: int | None


class MetricTransition(StrEnum):
    """Fenced writeの結果。"""

    PARTIAL = "partial"
    COMPLETED = "completed"
    DEFERRED = "deferred"
    FAILED = "failed"
    LEASE_LOST = "lease_lost"


class MetricCronRepository:
    """1つのDB Session内でMetrics state machineを操作する。"""

    def __init__(self, session: AsyncSession) -> None:
        """DB Sessionを受け取る。"""
        self._session = session

    async def terminalize_interrupted(self, now: datetime, max_attempts: int) -> list[int]:
        """最大試行の実行中にLease切れした行を外部Callなしで終端化する。"""
        stmt = (
            update(PostMetric)
            .where(
                PostMetric.status == PostMetricStatus.PENDING,
                PostMetric.attempt_count >= max_attempts,
                PostMetric.lease_expires_at.is_not(None),
                PostMetric.lease_expires_at <= now,
            )
            .values(
                status=PostMetricStatus.FAILED,
                execution_token=None,
                lease_expires_at=None,
                next_attempt_at=None,
                last_error_code="WORKER_INTERRUPTED",
            )
            .returning(PostMetric.post_id)
        )
        return list((await self._session.execute(stmt)).scalars())

    async def claim(
        self,
        *,
        now: datetime,
        lease_expires_at: datetime,
        max_attempts: int,
        limit: int,
        new_uuid: Callable[[], uuid.UUID],
    ) -> list[MetricClaim]:
        """実行可能行を順序付きでLockし、行ごとのTokenとLeaseを付与する。"""
        stmt = (
            select(PostMetric, Post, PostTrackingLink)
            .join(Post, Post.id == PostMetric.post_id)
            .join(PostTrackingLink, PostTrackingLink.post_id == Post.id)
            .where(
                PostMetric.status == PostMetricStatus.PENDING,
                PostMetric.scheduled_at <= now,
                or_(PostMetric.next_attempt_at.is_(None), PostMetric.next_attempt_at <= now),
                or_(PostMetric.lease_expires_at.is_(None), PostMetric.lease_expires_at <= now),
                PostMetric.attempt_count < max_attempts,
            )
            .order_by(PostMetric.scheduled_at, PostMetric.post_id)
            .limit(limit)
            .with_for_update(of=PostMetric, skip_locked=True)
        )
        claims: list[MetricClaim] = []
        for metric, post, tracking in (await self._session.execute(stmt)).tuples():
            token = new_uuid()
            metric.execution_token = token
            metric.lease_expires_at = lease_expires_at
            metric.attempt_count += 1
            metric.next_attempt_at = None
            claims.append(
                MetricClaim(
                    post_id=post.id,
                    token=token,
                    attempt_count=metric.attempt_count,
                    scheduled_at=metric.scheduled_at,
                    published_at=post.published_at,
                    x_post_id=post.x_post_id,
                    utm_source=tracking.utm_source,
                    utm_medium=tracking.utm_medium,
                    utm_campaign=tracking.utm_campaign,
                    utm_content=tracking.utm_content,
                    x_pv_count=metric.x_pv_count,
                    landing_user_count=metric.landing_user_count,
                )
            )
        await self._session.flush()
        return claims

    async def save_provider_success(
        self,
        post_id: int,
        token: uuid.UUID,
        *,
        provider: str,
        value: int,
        now: datetime,
    ) -> MetricTransition:
        """Provider値を保存し、両方揃えば同じTransactionで完了させる。"""
        metric = await self._held(post_id, token, now)
        if metric is None:
            return MetricTransition.LEASE_LOST
        if provider == "x":
            if metric.x_pv_count is None:
                metric.x_pv_count = value
        elif provider == "ga4":
            if metric.landing_user_count is None:
                metric.landing_user_count = value
        else:
            raise ValueError("unknown metric provider")
        if metric.x_pv_count is not None and metric.landing_user_count is not None:
            self._complete(metric, now)
            return MetricTransition.COMPLETED
        return MetricTransition.PARTIAL

    async def complete_if_ready(
        self, post_id: int, token: uuid.UUID, now: datetime
    ) -> MetricTransition:
        """中断で両値だけ保存済みの行をProvider再呼出しなしで完了させる。"""
        metric = await self._held(post_id, token, now)
        if metric is None:
            return MetricTransition.LEASE_LOST
        if metric.x_pv_count is None or metric.landing_user_count is None:
            return MetricTransition.PARTIAL
        self._complete(metric, now)
        return MetricTransition.COMPLETED

    async def finish_failure(
        self,
        post_id: int,
        token: uuid.UUID,
        *,
        now: datetime,
        error_code: str,
        retryable: bool,
        max_attempts: int,
    ) -> MetricTransition:
        """固定Errorだけを保存し、再試行または終端へ遷移する。"""
        metric = await self._held(post_id, token, now)
        if metric is None:
            return MetricTransition.LEASE_LOST
        if metric.x_pv_count is not None and metric.landing_user_count is not None:
            self._complete(metric, now)
            return MetricTransition.COMPLETED
        metric.execution_token = None
        metric.lease_expires_at = None
        metric.last_error_code = error_code
        if not retryable or metric.attempt_count >= max_attempts:
            metric.status = PostMetricStatus.FAILED
            metric.next_attempt_at = None
            return MetricTransition.FAILED
        metric.next_attempt_at = now + retry_delay(metric.attempt_count)
        return MetricTransition.DEFERRED

    async def _held(
        self, post_id: int, token: uuid.UUID, now: datetime
    ) -> PostMetric | None:
        stmt = (
            select(PostMetric)
            .where(
                PostMetric.post_id == post_id,
                PostMetric.status == PostMetricStatus.PENDING,
                PostMetric.execution_token == token,
                PostMetric.lease_expires_at > now,
            )
            .with_for_update()
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    @staticmethod
    def _complete(metric: PostMetric, now: datetime) -> None:
        metric.status = PostMetricStatus.COMPLETED
        metric.measured_at = now
        metric.execution_token = None
        metric.lease_expires_at = None
        metric.next_attempt_at = None
        metric.last_error_code = None
