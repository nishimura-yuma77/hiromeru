"""公開済み投稿と、その検索・トラッキング・計測のモデル。"""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from domain.constants import EMBEDDING_DIMENSIONS
from domain.enums import PostMetricStatus
from models.base import Base, created_at_column, hnsw_cosine_index, pg_enum, updated_at_column


class Post(Base):
    """X公開成功を確認した投稿だけを保存する。"""

    __tablename__ = "posts"
    __table_args__ = (Index("ix_posts_company_published", "company_id", "published_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("companies.id"))
    created_by_marketer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("marketers.id"))
    campaign_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("campaigns.id"))
    api_idempotency_request_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("api_idempotency_requests.id"), unique=True
    )
    body: Mapped[str] = mapped_column(Text)
    x_post_id: Mapped[str] = mapped_column(String(255), unique=True)
    published_at: Mapped[datetime]
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class PostEmbedding(Base):
    """公開済み投稿の意味検索に使う1対1の検索Projection。"""

    __tablename__ = "post_embeddings"
    __table_args__ = (
        Index("ix_post_embeddings_hash", "content_hash"),
        hnsw_cosine_index("ix_post_embeddings_hnsw", "embedding"),
    )

    post_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at_column()


class PostTrackingLink(Base):
    """UTM付きトラッキングURL。"""

    __tablename__ = "post_tracking_links"
    __table_args__ = (
        UniqueConstraint(
            "utm_source", "utm_medium", "utm_campaign", "utm_content", name="uq_tracking_utm"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    post_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("posts.id", ondelete="CASCADE"), unique=True
    )
    landing_url: Mapped[str] = mapped_column(Text)
    utm_source: Mapped[str] = mapped_column(String(255), server_default="x")
    utm_medium: Mapped[str] = mapped_column(String(255), server_default="social")
    utm_campaign: Mapped[str] = mapped_column(String(255))
    utm_content: Mapped[str] = mapped_column(String(255))
    tracked_url: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class PostMetric(Base):
    """投稿ごとの初週計測。投稿IDを主キーとして計測を冪等にする。"""

    __tablename__ = "post_metrics"
    __table_args__ = (
        Index(
            "ix_post_metrics_status_next_scheduled",
            "status",
            "next_attempt_at",
            "scheduled_at",
        ),
        Index(
            "ix_post_metrics_memory_retry",
            "memory_generated_at",
            "memory_failed_at",
            "memory_next_attempt_at",
        ),
        CheckConstraint(
            "status <> 'completed' OR (x_pv_count IS NOT NULL"
            " AND landing_user_count IS NOT NULL AND measured_at IS NOT NULL)",
            name="ck_post_metrics_completed",
        ),
        CheckConstraint(
            "(x_pv_count IS NULL OR x_pv_count >= 0)"
            " AND (landing_user_count IS NULL OR landing_user_count >= 0)",
            name="ck_post_metrics_non_negative",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND memory_attempt_count >= 0",
            name="ck_post_metrics_attempts_non_negative",
        ),
    )

    post_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("posts.id", ondelete="RESTRICT"), primary_key=True
    )
    scheduled_at: Mapped[datetime]
    status: Mapped[PostMetricStatus] = mapped_column(
        pg_enum(PostMetricStatus, "post_metric_status"), server_default="pending"
    )
    x_pv_count: Mapped[int | None] = mapped_column(BigInteger, default=None)
    landing_user_count: Mapped[int | None] = mapped_column(BigInteger, default=None)
    measured_at: Mapped[datetime | None] = mapped_column(default=None)
    execution_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    lease_expires_at: Mapped[datetime | None] = mapped_column(default=None)
    attempt_count: Mapped[int] = mapped_column(server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(default=None)
    last_error_code: Mapped[str | None] = mapped_column(String(255), default=None)
    memory_generated_at: Mapped[datetime | None] = mapped_column(default=None)
    memory_failed_at: Mapped[datetime | None] = mapped_column(default=None)
    memory_attempt_count: Mapped[int] = mapped_column(server_default="0")
    memory_next_attempt_at: Mapped[datetime | None] = mapped_column(default=None)
    memory_last_error_code: Mapped[str | None] = mapped_column(String(255), default=None)
