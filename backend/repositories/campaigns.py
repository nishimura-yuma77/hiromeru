"""施策とEmbeddingのRepository。"""

from datetime import datetime

from sqlalchemy import literal, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from domain.campaign_rules import CampaignContent
from models import Campaign, CampaignEmbedding
from repositories.vector import cosine_distance


class CampaignRepository:
    """施策のDBアクセス。すべて会社の条件を含める。"""

    def __init__(self, session: AsyncSession) -> None:
        """セッションを受け取る。"""
        self._session = session

    async def get(self, company_id: int, campaign_id: int) -> Campaign | None:
        """会社単位で施策を取得する。別会社の施策は None。"""
        stmt = select(Campaign).where(Campaign.id == campaign_id, Campaign.company_id == company_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def titles(self, company_id: int, campaign_ids: list[int]) -> dict[int, str]:
        """施策IDとタイトルの対応を返す。"""
        stmt = select(Campaign.id, Campaign.title).where(
            Campaign.company_id == company_id, Campaign.id.in_(campaign_ids)
        )
        return {row[0]: row[1] for row in await self._session.execute(stmt)}

    async def get_embedding_hash(self, campaign_id: int) -> str | None:
        """保存済みの検索用テキストのハッシュを返す。"""
        stmt = select(CampaignEmbedding.content_hash).where(
            CampaignEmbedding.campaign_id == campaign_id
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def insert(
        self, company_id: int, marketer_id: int, content: CampaignContent, now: datetime
    ) -> Campaign:
        """施策を新規作成する。"""
        campaign = Campaign(
            company_id=company_id,
            created_by_marketer_id=marketer_id,
            title=content.title,
            target_profile=content.target_profile,
            background=content.background,
            objective=content.objective,
            plan=content.plan,
            created_at=now,
            updated_at=now,
        )
        self._session.add(campaign)
        await self._session.flush()
        return campaign

    async def update_if_unchanged(
        self,
        company_id: int,
        campaign_id: int,
        expected_updated_at: datetime,
        content: CampaignContent,
        now: datetime,
    ) -> bool:
        """`updated_at` が期待値と一致する場合だけ全項目を上書きする（CAS）。

        `timestamptz` の値として比較する。更新できなければ False。
        """
        stmt = (
            update(Campaign)
            .where(
                Campaign.id == campaign_id,
                Campaign.company_id == company_id,
                Campaign.updated_at == expected_updated_at,
            )
            .values(
                title=content.title,
                target_profile=content.target_profile,
                background=content.background,
                objective=content.objective,
                plan=content.plan,
                updated_at=now,
            )
            .returning(Campaign.id)
        )
        return (await self._session.execute(stmt)).first() is not None

    async def upsert_embedding(
        self, campaign_id: int, vector: list[float], content_hash: str, now: datetime
    ) -> None:
        """検索用Embeddingを作成または更新する。"""
        stmt = pg_insert(CampaignEmbedding).values(
            campaign_id=campaign_id,
            embedding=vector,
            content_hash=content_hash,
            created_at=now,
            updated_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[CampaignEmbedding.campaign_id],
            set_={"embedding": vector, "content_hash": content_hash, "updated_at": now},
        )
        await self._session.execute(stmt)

    async def list_by_created(
        self,
        company_id: int,
        *,
        created_from: datetime | None,
        created_to: datetime | None,
        limit: int,
        after: tuple[datetime, int] | None,
    ) -> list[Campaign]:
        """`created_at` の降順（同じ場合は id の降順）で施策を返す。"""
        stmt = select(Campaign).where(
            Campaign.company_id == company_id, Campaign.archived_at.is_(None)
        )
        if created_from is not None:
            stmt = stmt.where(Campaign.created_at >= created_from)
        if created_to is not None:
            stmt = stmt.where(Campaign.created_at < created_to)
        if after is not None:
            stmt = stmt.where(
                tuple_(Campaign.created_at, Campaign.id)
                < tuple_(
                    literal(after[0], Campaign.created_at.type),
                    literal(after[1], Campaign.id.type),
                )
            )
        stmt = stmt.order_by(Campaign.created_at.desc(), Campaign.id.desc()).limit(limit)
        return list((await self._session.execute(stmt)).scalars())

    async def search(
        self,
        company_id: int,
        vector: list[float],
        *,
        created_from: datetime | None,
        created_to: datetime | None,
        limit: int,
    ) -> list[tuple[Campaign, float]]:
        """コサイン類似度の高い順に施策を返す。"""
        distance = cosine_distance(CampaignEmbedding.embedding, vector)
        stmt = (
            select(Campaign, (1 - distance).label("similarity"))
            .join(CampaignEmbedding, CampaignEmbedding.campaign_id == Campaign.id)
            .where(Campaign.company_id == company_id, Campaign.archived_at.is_(None))
        )
        if created_from is not None:
            stmt = stmt.where(Campaign.created_at >= created_from)
        if created_to is not None:
            stmt = stmt.where(Campaign.created_at < created_to)
        stmt = stmt.order_by(distance, Campaign.id.desc()).limit(limit)
        return [(row[0], float(row[1])) for row in await self._session.execute(stmt)]
