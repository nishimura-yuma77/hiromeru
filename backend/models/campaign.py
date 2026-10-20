"""施策と、その検索用Embeddingのモデル。"""

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, ForeignKey, ForeignKeyConstraint, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from domain.constants import EMBEDDING_DIMENSIONS
from models.base import Base, created_at_column, hnsw_cosine_index, updated_at_column


class Campaign(Base):
    """マーケティング施策。"""

    __tablename__ = "campaigns"
    __table_args__ = (
        Index("ix_campaigns_company_created", "company_id", "created_at"),
        # 作成者が施策と同じ会社に所属することをDBで保証する。
        ForeignKeyConstraint(
            ["created_by_user_id", "company_id"],
            ["users.id", "users.company_id"],
            name="fk_campaigns_creator_company",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("companies.id"))
    created_by_user_id: Mapped[int] = mapped_column(BigInteger)
    title: Mapped[str] = mapped_column(String(255))
    target_profile: Mapped[str] = mapped_column(Text)
    background: Mapped[str] = mapped_column(Text)
    objective: Mapped[str] = mapped_column(Text)
    plan: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
    archived_at: Mapped[datetime | None] = mapped_column(default=None)


class CampaignEmbedding(Base):
    """施策の意味検索に使う1対1の検索Projection。"""

    __tablename__ = "campaign_embeddings"
    __table_args__ = (
        Index("ix_campaign_embeddings_hash", "content_hash"),
        hnsw_cosine_index("ix_campaign_embeddings_hnsw", "embedding"),
    )

    campaign_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
