"""Agentのセッション・ターン・アイテムと、その監査記録のモデル。"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from domain.enums import (
    AgentContentSource,
    AgentContextClass,
    AgentItemContextStatus,
    AgentItemType,
    AgentTurnStatus,
    AgentType,
    SecurityDetector,
    SecurityEnforcement,
    SecurityEventType,
    ToolExecutionStatus,
)
from models.base import Base, created_at_column, pg_enum, updated_at_column


class AgentSession(Base):
    """1つのエージェントが所有する再開可能な会話。"""

    __tablename__ = "agent_sessions"
    __table_args__ = (
        UniqueConstraint("id", "marketer_id", name="uq_agent_sessions_id_marketer"),
        ForeignKeyConstraint(
            ["parent_session_id", "marketer_id"],
            ["agent_sessions.id", "agent_sessions.marketer_id"],
            name="fk_agent_sessions_parent",
        ),
        Index("ix_agent_sessions_marketer_updated", "marketer_id", "updated_at"),
        Index("ix_agent_sessions_parent_created", "parent_session_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    marketer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("marketers.id"))
    parent_session_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    agent: Mapped[AgentType] = mapped_column(pg_enum(AgentType, "agent_type"))
    title: Mapped[str | None] = mapped_column(String(255), default=None)
    archived_at: Mapped[datetime | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class AgentTurn(Base):
    """1つの入力から回答までのエージェントループ。"""

    __tablename__ = "agent_turns"
    __table_args__ = (
        UniqueConstraint("session_id", "turn_number", name="uq_agent_turns_session_number"),
        UniqueConstraint("id", "session_id", name="uq_agent_turns_id_session"),
        Index("ix_agent_turns_session_created", "session_id", "created_at"),
        Index("ix_agent_turns_status_created", "status", "created_at"),
        CheckConstraint("turn_number >= 1", name="ck_agent_turns_number"),
        CheckConstraint("next_item_number >= 1", name="ck_agent_turns_next_item"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    session_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("agent_sessions.id"))
    turn_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[AgentTurnStatus] = mapped_column(
        pg_enum(AgentTurnStatus, "agent_turn_status"), server_default="pending"
    )
    next_item_number: Mapped[int] = mapped_column(Integer, server_default="1")
    error_code: Mapped[str | None] = mapped_column(String(100), default=None)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)
    started_at: Mapped[datetime | None] = mapped_column(default=None)
    completed_at: Mapped[datetime | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class LlmCall(Base):
    """LLM呼び出しの記録。"""

    __tablename__ = "llm_calls"
    __table_args__ = (
        Index("ix_llm_calls_turn_called", "agent_turn_id", "called_at"),
        UniqueConstraint("id", "agent_turn_id", name="uq_llm_calls_id_turn"),
        CheckConstraint(
            "(input_tokens IS NULL OR input_tokens >= 0)"
            " AND (output_tokens IS NULL OR output_tokens >= 0)"
            " AND (cost_usd IS NULL OR cost_usd >= 0)"
            " AND (response_time_ms IS NULL OR response_time_ms >= 0)",
            name="ck_llm_calls_non_negative",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    agent_turn_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("agent_turns.id"))
    orcarouter_request_id: Mapped[str | None] = mapped_column(
        String(255), unique=True, default=None
    )
    input_tokens: Mapped[int | None] = mapped_column(Integer, default=None)
    output_tokens: Mapped[int | None] = mapped_column(Integer, default=None)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), default=None)
    response_time_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    succeeded: Mapped[bool] = mapped_column(Boolean)
    error_code: Mapped[str | None] = mapped_column(String(100), default=None)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)
    called_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class AgentItem(Base):
    """1ターン内の順序付き履歴。内容は追記後に変更しない。"""

    __tablename__ = "agent_items"
    __table_args__ = (
        UniqueConstraint("id", "agent_turn_id", name="uq_agent_items_id_turn"),
        UniqueConstraint("agent_turn_id", "item_number", name="uq_agent_items_turn_number"),
        UniqueConstraint("agent_turn_id", "idempotency_key", name="uq_agent_items_turn_key"),
        UniqueConstraint(
            "related_tool_call_item_id", "item_type", name="uq_agent_items_related_type"
        ),
        ForeignKeyConstraint(
            ["related_tool_call_item_id", "agent_turn_id"],
            ["agent_items.id", "agent_items.agent_turn_id"],
            name="fk_agent_items_related",
        ),
        ForeignKeyConstraint(
            ["llm_call_id", "agent_turn_id"],
            ["llm_calls.id", "llm_calls.agent_turn_id"],
            name="fk_agent_items_llm_call",
        ),
        Index("ix_agent_items_llm_call", "llm_call_id"),
        CheckConstraint("item_number >= 1", name="ck_agent_items_number"),
        CheckConstraint(
            "(item_type = 'tool_result') = (related_tool_call_item_id IS NOT NULL)",
            name="ck_agent_items_tool_result_ref",
        ),
        CheckConstraint(
            "(context_status = 'quarantined' AND quarantine_reason IS NOT NULL"
            " AND context_override IS NOT NULL AND quarantined_at IS NOT NULL)"
            " OR (context_status = 'active' AND quarantine_reason IS NULL"
            " AND context_override IS NULL AND quarantined_at IS NULL)",
            name="ck_agent_items_quarantine",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    agent_turn_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("agent_turns.id"))
    related_tool_call_item_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    llm_call_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    item_number: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(255))
    item_type: Mapped[AgentItemType] = mapped_column(pg_enum(AgentItemType, "agent_item_type"))
    context_class: Mapped[AgentContextClass] = mapped_column(
        pg_enum(AgentContextClass, "agent_context_class")
    )
    content_source: Mapped[AgentContentSource] = mapped_column(
        pg_enum(AgentContentSource, "agent_content_source")
    )
    context_status: Mapped[AgentItemContextStatus] = mapped_column(
        pg_enum(AgentItemContextStatus, "agent_item_context_status"), server_default="active"
    )
    quarantine_reason: Mapped[str | None] = mapped_column(String(100), default=None)
    context_override: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), default=None
    )
    quarantined_at: Mapped[datetime | None] = mapped_column(default=None)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at_column()


class ToolExecution(Base):
    """1つの論理的なtool_callアイテムに対する最小限の実行状態。"""

    __tablename__ = "tool_executions"
    __table_args__ = (CheckConstraint("attempt_count >= 0", name="ck_tool_executions_attempt"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tool_call_item_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("agent_items.id"), unique=True
    )
    status: Mapped[ToolExecutionStatus] = mapped_column(
        pg_enum(ToolExecutionStatus, "tool_execution_status"), server_default="pending"
    )
    attempt_count: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = created_at_column()
    completed_at: Mapped[datetime | None] = mapped_column(default=None)


class AgentContextCheckpoint(Base):
    """完了済みターンの境界で作るコンテキスト要約。"""

    __tablename__ = "agent_context_checkpoints"
    __table_args__ = (
        ForeignKeyConstraint(
            ["compacted_through_turn_id", "session_id"],
            ["agent_turns.id", "agent_turns.session_id"],
            name="fk_checkpoints_turn_session",
        ),
        Index("ix_checkpoints_session_through", "session_id", "compacted_through_turn_id"),
        Index("ix_checkpoints_session_created", "session_id", "created_at"),
        # 同じターン境界で有効なチェックポイントを最大1件に制限する。
        Index(
            "uq_checkpoints_active_boundary",
            "session_id",
            "compacted_through_turn_id",
            unique=True,
            postgresql_where=text("invalidated_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    session_id: Mapped[int] = mapped_column(BigInteger)
    compacted_through_turn_id: Mapped[int] = mapped_column(BigInteger)
    summary: Mapped[str] = mapped_column(Text)
    invalidated_at: Mapped[datetime | None] = mapped_column(default=None)
    invalidation_reason: Mapped[str | None] = mapped_column(String(100), default=None)
    created_at: Mapped[datetime] = created_at_column()


class SecurityEvent(Base):
    """1ターン内で検出した追記専用の監査記録。"""

    __tablename__ = "security_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agent_item_id", "agent_turn_id"],
            ["agent_items.id", "agent_items.agent_turn_id"],
            name="fk_security_events_item_turn",
        ),
        ForeignKeyConstraint(
            ["llm_call_id", "agent_turn_id"],
            ["llm_calls.id", "llm_calls.agent_turn_id"],
            name="fk_security_events_llm_turn",
        ),
        UniqueConstraint("detector", "external_event_id", name="uq_security_events_external"),
        Index("ix_security_events_type_detected", "event_type", "detected_at"),
        Index("ix_security_events_turn", "agent_turn_id"),
        Index("ix_security_events_item", "agent_item_id"),
        Index("ix_security_events_llm_call", "llm_call_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    agent_turn_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("agent_turns.id"))
    agent_item_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    llm_call_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    event_type: Mapped[SecurityEventType] = mapped_column(
        pg_enum(SecurityEventType, "security_event_type")
    )
    detector: Mapped[SecurityDetector] = mapped_column(
        pg_enum(SecurityDetector, "security_detector")
    )
    source: Mapped[AgentContentSource] = mapped_column(
        pg_enum(AgentContentSource, "agent_content_source")
    )
    enforcement: Mapped[SecurityEnforcement] = mapped_column(
        pg_enum(SecurityEnforcement, "security_enforcement")
    )
    external_event_id: Mapped[str | None] = mapped_column(String(255), default=None)
    summary: Mapped[str] = mapped_column(Text)
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, server_default=text("'{}'::jsonb")
    )
    detected_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
