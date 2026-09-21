"""テストデータをDBへ直接用意する補助（APIで作れないデータ用）。"""

from datetime import UTC, datetime

from sqlalchemy import select

from domain.enums import PostMetricStatus
from models import AgentMemory, MemoryCampaign, MemoryPost, Post, PostMetric
from repositories.database import SessionLocal
from tests.support.fakes import vector_for


async def insert_memory(
    company_id: int,
    content: str,
    *,
    campaign_ids: tuple[int, ...] = (),
    post_ids: tuple[int, ...] = (),
) -> int:
    """記憶と、施策・投稿との関連を作る。"""
    async with SessionLocal() as session, session.begin():
        memory = AgentMemory(company_id=company_id, content=content, embedding=vector_for(content))
        session.add(memory)
        await session.flush()
        session.add_all(MemoryCampaign(memory_id=memory.id, campaign_id=c) for c in campaign_ids)
        session.add_all(MemoryPost(memory_id=memory.id, post_id=p) for p in post_ids)
        return memory.id


async def complete_metrics(post_id: int, *, x_pv_count: int, landing_user_count: int) -> None:
    """投稿の計測を完了にする。"""
    async with SessionLocal() as session, session.begin():
        metric = (
            await session.execute(select(PostMetric).where(PostMetric.post_id == post_id))
        ).scalar_one()
        metric.status = PostMetricStatus.COMPLETED
        metric.x_pv_count = x_pv_count
        metric.landing_user_count = landing_user_count
        metric.measured_at = datetime.now(UTC)


async def post_ids_of_campaign(campaign_id: int) -> list[int]:
    """施策に紐づく投稿IDを返す。"""
    async with SessionLocal() as session:
        rows = await session.execute(select(Post.id).where(Post.campaign_id == campaign_id))
        return list(rows.scalars())
