"""施策upsertとX投稿に共通する永続的な冪等性制御のモデル。"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from domain.enums import ApiIdempotencyStatus, ApiOperation
from models.base import Base, created_at_column, pg_enum, updated_at_column


class ApiIdempotencyRequest(Base):
    """API冪等性Request。最初のRequestだけがprocessing行の作成に成功して実行権を得る。"""

    __tablename__ = "api_idempotency_requests"
    __table_args__ = (
        UniqueConstraint(
            "marketer_id", "operation", "idempotency_key", name="uq_air_marketer_op_key"
        ),
        ForeignKeyConstraint(
            ["session_id", "marketer_id"],
            ["agent_sessions.id", "agent_sessions.marketer_id"],
            name="fk_air_session_marketer",
        ),
        ForeignKeyConstraint(
            ["agent_turn_id", "session_id"],
            ["agent_turns.id", "agent_turns.session_id"],
            name="fk_air_turn_session",
        ),
        Index("ix_air_session_created", "session_id", "created_at"),
        Index("ix_air_status_lease", "status", "lease_expires_at"),
        # request_hash の照合（X_POST_UNRESOLVED の判定）に使う。
        Index("ix_air_marketer_op_hash", "marketer_id", "operation", "request_hash"),
        CheckConstraint(
            "(status = 'processing' AND http_status IS NULL AND response_body IS NULL"
            " AND completed_at IS NULL)"
            " OR (status <> 'processing' AND http_status IS NOT NULL"
            " AND response_body IS NOT NULL AND completed_at IS NOT NULL)",
            name="ck_air_response_fields",
        ),
        CheckConstraint(
            "external_result IS NULL OR (operation = 'publish_x_post'"
            " AND external_effect_started_at IS NOT NULL)",
            name="ck_air_external_result",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    marketer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("marketers.id"))
    session_id: Mapped[int] = mapped_column(BigInteger)
    agent_turn_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, default=None)
    operation: Mapped[ApiOperation] = mapped_column(pg_enum(ApiOperation, "api_operation"))
    idempotency_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[ApiIdempotencyStatus] = mapped_column(
        pg_enum(ApiIdempotencyStatus, "api_idempotency_status"), server_default="processing"
    )
    execution_token: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    lease_expires_at: Mapped[datetime]
    external_effect_started_at: Mapped[datetime | None] = mapped_column(default=None)
    external_result: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), default=None
    )
    http_status: Mapped[int | None] = mapped_column(SmallInteger, default=None)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), default=None
    )
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
    completed_at: Mapped[datetime | None] = mapped_column(default=None)
