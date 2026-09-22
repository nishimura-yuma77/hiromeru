"""長期記憶のRepository。"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, literal, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from domain.enums import ApiIdempotencyStatus, ApiOperation
from models import (
    AgentMemory,
    ApiIdempotencyRequest,
    Campaign,
    MemoryCampaign,
    MemoryPost,
    Post,
)
from repositories.vector import cosine_distance


@dataclass(frozen=True)
class MemoryRow:
    """記憶の1行（Embeddingは読み込まない）。"""

    id: int
    content: str
    similarity: float | None = None


@dataclass(frozen=True)
class MemoryRelations:
    """記憶に関連付けられた施策と投稿。"""

    campaigns: dict[int, list[tuple[int, str, datetime | None]]]
    posts: dict[int, list[tuple[int, datetime]]]


class MemoryRepository:
    """記憶のDBアクセス。すべて会社の条件を含める。"""

    def __init__(self, session: AsyncSession) -> None:
        """セッションを受け取る。"""
        self._session = session

    async def delete(self, company_id: int, memory_id: int) -> bool:
        """記憶（内容とEmbedding）を削除する。関連行は外部キーの cascade で同時に削除される。

        会社の条件を含む1つのDELETEで行うため、同時に届いた複数のRequestのうち、
        削除できるのは1つだけになる。
        """
        stmt = (
            delete(AgentMemory)
            .where(AgentMemory.id == memory_id, AgentMemory.company_id == company_id)
            .returning(AgentMemory.id)
        )
        return (await self._session.execute(stmt)).first() is not None

    async def list_recent(
        self,
        company_id: int,
        *,
        campaign_id: int | None,
        limit: int,
        after_id: int | None,
    ) -> list[MemoryRow]:
        """Id の降順（採番の新しい順）で記憶を返す。"""
        stmt = select(AgentMemory.id, AgentMemory.content).where(
            AgentMemory.company_id == company_id
        )
        if campaign_id is not None:
            stmt = stmt.join(MemoryCampaign).where(MemoryCampaign.campaign_id == campaign_id)
        if after_id is not None:
            stmt = stmt.where(AgentMemory.id < after_id)
        stmt = stmt.order_by(AgentMemory.id.desc()).limit(limit)
        return [MemoryRow(r[0], r[1]) for r in await self._session.execute(stmt)]

    async def search(
        self, company_id: int, vector: list[float], campaign_id: int | None, limit: int
    ) -> list[MemoryRow]:
        """コサイン類似度の高い順に記憶を返す。"""
        distance = cosine_distance(AgentMemory.embedding, vector)
        stmt = select(
            AgentMemory.id, AgentMemory.content, (1 - distance).label("similarity")
        ).where(AgentMemory.company_id == company_id)
        if campaign_id is not None:
            stmt = stmt.join(MemoryCampaign).where(MemoryCampaign.campaign_id == campaign_id)
        stmt = stmt.order_by(distance, AgentMemory.id.desc()).limit(limit)
        return [MemoryRow(r[0], r[1], float(r[2])) for r in await self._session.execute(stmt)]

    async def exists(self, company_id: int, memory_id: int) -> bool:
        """会社単位で記憶が存在するか返す。"""
        stmt = select(AgentMemory.id).where(
            AgentMemory.id == memory_id, AgentMemory.company_id == company_id
        )
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None

    async def related_campaigns(
        self, company_id: int, memory_id: int, *, limit: int, after_id: int | None
    ) -> list[tuple[int, str, datetime | None]]:
        """関連施策を施策IDの降順で返す。"""
        stmt = (
            select(Campaign.id, Campaign.title, Campaign.archived_at)
            .join(MemoryCampaign, MemoryCampaign.campaign_id == Campaign.id)
            .where(
                MemoryCampaign.memory_id == memory_id,
                Campaign.company_id == company_id,
            )
        )
        if after_id is not None:
            stmt = stmt.where(Campaign.id < after_id)
        result = await self._session.execute(stmt.order_by(Campaign.id.desc()).limit(limit))
        return list(result.tuples())

    async def related_posts(
        self,
        company_id: int,
        memory_id: int,
        *,
        limit: int,
        after: tuple[datetime, int] | None,
    ) -> list[tuple[int, datetime]]:
        """公開成功済みの関連投稿を公開日時・IDの降順で返す。"""
        stmt = (
            select(Post.id, Post.published_at)
            .join(MemoryPost, MemoryPost.post_id == Post.id)
            .join(
                ApiIdempotencyRequest,
                ApiIdempotencyRequest.id == Post.api_idempotency_request_id,
            )
            .where(
                MemoryPost.memory_id == memory_id,
                Post.company_id == company_id,
                ApiIdempotencyRequest.operation == ApiOperation.PUBLISH_X_POST,
                ApiIdempotencyRequest.status == ApiIdempotencyStatus.SUCCEEDED,
            )
        )
        if after is not None:
            stmt = stmt.where(
                tuple_(Post.published_at, Post.id) < tuple_(literal(after[0]), literal(after[1]))
            )
        stmt = stmt.order_by(Post.published_at.desc(), Post.id.desc()).limit(limit)
        return list((await self._session.execute(stmt)).tuples())

    async def list_for_campaign(
        self, company_id: int, campaign_id: int, limit: int
    ) -> list[MemoryRow]:
        """施策に関連付けられた記憶を id の降順で返す。"""
        stmt = (
            select(AgentMemory.id, AgentMemory.content)
            .join(MemoryCampaign, MemoryCampaign.memory_id == AgentMemory.id)
            .where(AgentMemory.company_id == company_id, MemoryCampaign.campaign_id == campaign_id)
            .order_by(AgentMemory.id.desc())
            .limit(limit)
        )
        return [MemoryRow(r[0], r[1]) for r in await self._session.execute(stmt)]

    async def relations(self, company_id: int, memory_ids: list[int]) -> MemoryRelations:
        """記憶に関連付けられた施策と投稿を、まとめて取得する（N+1を避ける）。"""
        campaigns: dict[int, list[tuple[int, str, datetime | None]]] = defaultdict(list)
        posts: dict[int, list[tuple[int, datetime]]] = defaultdict(list)
        if not memory_ids:
            return MemoryRelations(campaigns, posts)
        campaign_stmt = (
            select(MemoryCampaign.memory_id, Campaign.id, Campaign.title, Campaign.archived_at)
            .join(Campaign, Campaign.id == MemoryCampaign.campaign_id)
            .where(MemoryCampaign.memory_id.in_(memory_ids), Campaign.company_id == company_id)
            .order_by(MemoryCampaign.memory_id, Campaign.id.desc())
        )
        for memory_id, campaign_id, title, archived_at in await self._session.execute(
            campaign_stmt
        ):
            campaigns[memory_id].append((campaign_id, title, archived_at))
        post_stmt = (
            select(MemoryPost.memory_id, Post.id, Post.published_at)
            .join(Post, Post.id == MemoryPost.post_id)
            .join(
                ApiIdempotencyRequest,
                ApiIdempotencyRequest.id == Post.api_idempotency_request_id,
            )
            .where(
                MemoryPost.memory_id.in_(memory_ids),
                Post.company_id == company_id,
                ApiIdempotencyRequest.operation == ApiOperation.PUBLISH_X_POST,
                ApiIdempotencyRequest.status == ApiIdempotencyStatus.SUCCEEDED,
            )
            .order_by(MemoryPost.memory_id, Post.published_at.desc(), Post.id.desc())
        )
        for memory_id, post_id, published_at in await self._session.execute(post_stmt):
            posts[memory_id].append((post_id, published_at))
        return MemoryRelations(campaigns, posts)
