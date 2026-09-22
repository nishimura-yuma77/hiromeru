"""会社単位の長期記憶のモデル。"""

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from domain.constants import EMBEDDING_DIMENSIONS
from models.base import Base, hnsw_cosine_index


class AgentMemory(Base):
    """会社単位の長期記憶。施策・投稿との関連がなくても保持できる。"""

    __tablename__ = "agent_memories"
    __table_args__ = (
        Index("ix_agent_memories_company", "company_id"),
        hnsw_cosine_index("ix_agent_memories_hnsw", "embedding"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("companies.id"))
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))


class MemoryCampaign(Base):
    """記憶と施策の関連。"""

    __tablename__ = "memory_campaigns"
    __table_args__ = (Index("ix_memory_campaigns_campaign", "campaign_id"),)

    memory_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("agent_memories.id", ondelete="CASCADE"), primary_key=True
    )
    campaign_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True
    )


class MemoryPost(Base):
    """記憶と投稿の関連。"""

    __tablename__ = "memory_posts"
    __table_args__ = (Index("ix_memory_posts_post", "post_id"),)

    memory_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("agent_memories.id", ondelete="CASCADE"), primary_key=True
    )
    post_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True
    )
