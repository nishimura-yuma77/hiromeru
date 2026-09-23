"""評価記憶Cronの独立ClaimとFencing付き状態遷移。"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from domain.cron import retry_delay
from domain.enums import PostMetricStatus
from models import Campaign, Post, PostMetric
from repositories.memories import MemoryRepository


@dataclass(frozen=True)
class EvaluationMemoryClaim:
    """Embedding生成へ渡すClaim時点のSnapshot。"""

    post_id: int
    company_id: int
    campaign_id: int
    campaign_title: str
    post_body: str
    x_pv_count: int
    landing_user_count: int
    scheduled_at: datetime
    token: uuid.UUID
    attempt_count: int


class MemoryTransition(StrEnum):
    """評価記憶のFenced write結果。"""

    CREATED = "created"
    DEFERRED = "deferred"
    FAILED = "failed"
    LEASE_LOST = "lease_lost"


class MemoryCronRepository:
    """1つのDB Session内で評価記憶state machineを操作する。"""

    def __init__(self, session: AsyncSession) -> None:
        """DB Sessionを受け取る。"""
        self._session = session

    async def terminalize_interrupted(self, now: datetime, max_attempts: int) -> list[int]:
        """最大試行のLease切れをMetrics状態を変えず終端化する。"""
        stmt = (
            update(PostMetric)
            .where(
                PostMetric.status == PostMetricStatus.COMPLETED,
                PostMetric.memory_generated_at.is_(None),
                PostMetric.memory_failed_at.is_(None),
                PostMetric.memory_attempt_count >= max_attempts,
                PostMetric.lease_expires_at.is_not(None),
                PostMetric.lease_expires_at <= now,
            )
            .values(
                memory_failed_at=now,
                memory_next_attempt_at=None,
                memory_last_error_code="WORKER_INTERRUPTED",
                execution_token=None,
                lease_expires_at=None,
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
    ) -> list[EvaluationMemoryClaim]:
        """Metrics完了済み行へ新しい記憶専用TokenとLeaseを設定する。"""
        stmt = (
            select(PostMetric, Post, Campaign)
            .join(Post, Post.id == PostMetric.post_id)
            .join(
                Campaign,
                and_(Campaign.id == Post.campaign_id, Campaign.company_id == Post.company_id),
            )
            .where(
                PostMetric.status == PostMetricStatus.COMPLETED,
                PostMetric.memory_generated_at.is_(None),
                PostMetric.memory_failed_at.is_(None),
                or_(
                    PostMetric.memory_next_attempt_at.is_(None),
                    PostMetric.memory_next_attempt_at <= now,
                ),
                or_(PostMetric.lease_expires_at.is_(None), PostMetric.lease_expires_at <= now),
                PostMetric.memory_attempt_count < max_attempts,
            )
            .order_by(PostMetric.scheduled_at, PostMetric.post_id)
            .limit(limit)
            .with_for_update(of=PostMetric, skip_locked=True)
        )
        claims: list[EvaluationMemoryClaim] = []
        for metric, post, campaign in (await self._session.execute(stmt)).tuples():
            token = new_uuid()
            metric.execution_token = token
            metric.lease_expires_at = lease_expires_at
            metric.memory_attempt_count += 1
            metric.memory_next_attempt_at = None
            if metric.x_pv_count is None or metric.landing_user_count is None:
                raise RuntimeError("completed metrics must contain both provider values")
            claims.append(
                EvaluationMemoryClaim(
                    post_id=post.id,
                    company_id=post.company_id,
                    campaign_id=campaign.id,
                    campaign_title=campaign.title,
                    post_body=post.body,
                    x_pv_count=metric.x_pv_count,
                    landing_user_count=metric.landing_user_count,
                    scheduled_at=metric.scheduled_at,
                    token=token,
                    attempt_count=metric.memory_attempt_count,
                )
            )
        await self._session.flush()
        return claims

    async def save_created(
        self,
        claim: EvaluationMemoryClaim,
        *,
        content: str,
        embedding: list[float],
        now: datetime,
    ) -> tuple[MemoryTransition, int | None]:
        """記憶・両Relation・生成Markerを1つのFenced Transactionへ追加する。"""
        metric = await self._held(claim.post_id, claim.token, now)
        if metric is None:
            return MemoryTransition.LEASE_LOST, None
        memory = await MemoryRepository(self._session).insert(
            claim.company_id,
            content,
            embedding,
            (claim.campaign_id,),
            (claim.post_id,),
        )
        metric.memory_generated_at = now
        metric.memory_next_attempt_at = None
        metric.memory_last_error_code = None
        metric.execution_token = None
        metric.lease_expires_at = None
        return MemoryTransition.CREATED, memory.id

    async def finish_failure(
        self,
        post_id: int,
        token: uuid.UUID,
        *,
        now: datetime,
        error_code: str,
        max_attempts: int,
    ) -> MemoryTransition:
        """Metricsをcompletedのまま、記憶だけを再試行または終端化する。"""
        metric = await self._held(post_id, token, now)
        if metric is None:
            return MemoryTransition.LEASE_LOST
        metric.execution_token = None
        metric.lease_expires_at = None
        metric.memory_last_error_code = error_code
        if metric.memory_attempt_count >= max_attempts:
            metric.memory_failed_at = now
            metric.memory_next_attempt_at = None
            return MemoryTransition.FAILED
        metric.memory_next_attempt_at = now + retry_delay(metric.memory_attempt_count)
        return MemoryTransition.DEFERRED

    async def _held(
        self, post_id: int, token: uuid.UUID, now: datetime
    ) -> PostMetric | None:
        stmt = (
            select(PostMetric)
            .where(
                PostMetric.post_id == post_id,
                PostMetric.status == PostMetricStatus.COMPLETED,
                PostMetric.execution_token == token,
                PostMetric.lease_expires_at > now,
                PostMetric.memory_generated_at.is_(None),
                PostMetric.memory_failed_at.is_(None),
            )
            .with_for_update()
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()
