"""一覧APIの短期Snapshotモデル。"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, created_at_column


class ApiListSnapshot(Base):
    """投稿・指標一覧をPage間で固定する短期Snapshot。"""

    __tablename__ = "api_list_snapshots"
    __table_args__ = (
        Index(
            "ix_api_list_snapshots_owner_resource_expiry", "marketer_id", "resource", "expires_at"
        ),
        Index("ix_api_list_snapshots_expiry", "expires_at"),
        CheckConstraint("resource IN ('posts', 'metrics')", name="ck_api_list_snapshots_resource"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    marketer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("marketers.id", ondelete="CASCADE")
    )
    resource: Mapped[str] = mapped_column(String(50))
    filter_hash: Mapped[str] = mapped_column(String(64))
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True), default=None)
    created_at: Mapped[datetime] = created_at_column()
    expires_at: Mapped[datetime]


class ApiListSnapshotItem(Base):
    """Snapshot内の順序と固定済みProjection。"""

    __tablename__ = "api_list_snapshot_items"
    __table_args__ = (CheckConstraint("position >= 0", name="ck_api_list_snapshot_items_position"),)

    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("api_list_snapshots.id", ondelete="CASCADE"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    item: Mapped[dict[str, Any]] = mapped_column(JSONB)
