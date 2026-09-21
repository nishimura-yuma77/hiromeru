"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-09-21 17:32:42.027398

"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    # BE_STD 13章: 最初のマイグレーションで vector 拡張を有効にする。
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    postgresql.ENUM("parent", "campaign_planner", "content_creator", name="agent_type").create(bind)
    postgresql.ENUM(
        "pending",
        "running",
        "completed",
        "failed",
        "cancelled",
        "blocked",
        name="agent_turn_status",
    ).create(bind)
    postgresql.ENUM("upsert_campaign", "publish_x_post", name="api_operation").create(bind)
    postgresql.ENUM(
        "processing",
        "succeeded",
        "failed",
        "outcome_unknown",
        name="api_idempotency_status",
    ).create(bind)
    postgresql.ENUM(
        "user_message",
        "assistant_message",
        "tool_call",
        "tool_result",
        name="agent_item_type",
    ).create(bind)
    postgresql.ENUM("conversation", "untrusted_data", name="agent_context_class").create(bind)
    postgresql.ENUM(
        "user_input",
        "user_document",
        "agent_output",
        "web_content",
        "web_search",
        "database",
        "long_term_memory",
        "external_api",
        "mcp_tool",
        "system",
        name="agent_content_source",
    ).create(bind)
    postgresql.ENUM("active", "quarantined", name="agent_item_context_status").create(bind)
    postgresql.ENUM("pending", "completed", "failed", name="post_metric_status").create(bind)
    postgresql.ENUM(
        "prompt_injection",
        "sensitive_data",
        "unauthorized_tool_call",
        "unsafe_external_action",
        name="security_event_type",
    ).create(bind)
    postgresql.ENUM(
        "application",
        "orcarouter_guardrail",
        "orcarouter_firewall",
        name="security_detector",
    ).create(bind)
    postgresql.ENUM("observed", "sanitized", "blocked", name="security_enforcement").create(bind)
    postgresql.ENUM(
        "pending",
        "running",
        "completed",
        "failed",
        "cancelled",
        "blocked",
        name="tool_execution_status",
    ).create(bind)
    op.create_table(
        "companies",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "agent_memories",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=1536), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_memories_company", "agent_memories", ["company_id"], unique=False)
    op.create_index(
        "ix_agent_memories_hnsw",
        "agent_memories",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_table(
        "marketers",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_table(
        "agent_sessions",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("marketer_id", sa.BigInteger(), nullable=False),
        sa.Column("parent_session_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "agent",
            postgresql.ENUM(name="agent_type", create_type=False),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["marketer_id"],
            ["marketers.id"],
        ),
        sa.ForeignKeyConstraint(
            ["parent_session_id", "marketer_id"],
            ["agent_sessions.id", "agent_sessions.marketer_id"],
            name="fk_agent_sessions_parent",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "marketer_id", name="uq_agent_sessions_id_marketer"),
    )
    op.create_index(
        "ix_agent_sessions_marketer_updated",
        "agent_sessions",
        ["marketer_id", "updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_agent_sessions_parent_created",
        "agent_sessions",
        ["parent_session_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "campaigns",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column("created_by_marketer_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("target_profile", sa.Text(), nullable=False),
        sa.Column("background", sa.Text(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("plan", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
        ),
        sa.ForeignKeyConstraint(
            ["created_by_marketer_id"],
            ["marketers.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_campaigns_company_created",
        "campaigns",
        ["company_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "agent_turns",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("session_id", sa.BigInteger(), nullable=False),
        sa.Column("turn_number", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="agent_turn_status", create_type=False),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("next_item_number", sa.Integer(), server_default="1", nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("next_item_number >= 1", name="ck_agent_turns_next_item"),
        sa.CheckConstraint("turn_number >= 1", name="ck_agent_turns_number"),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["agent_sessions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "session_id", name="uq_agent_turns_id_session"),
        sa.UniqueConstraint("session_id", "turn_number", name="uq_agent_turns_session_number"),
    )
    op.create_index(
        "ix_agent_turns_session_created",
        "agent_turns",
        ["session_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_agent_turns_status_created",
        "agent_turns",
        ["status", "created_at"],
        unique=False,
    )
    op.create_table(
        "campaign_embeddings",
        sa.Column("campaign_id", sa.BigInteger(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=1536), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("campaign_id"),
    )
    op.create_index(
        "ix_campaign_embeddings_hash",
        "campaign_embeddings",
        ["content_hash"],
        unique=False,
    )
    op.create_index(
        "ix_campaign_embeddings_hnsw",
        "campaign_embeddings",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_table(
        "memory_campaigns",
        sa.Column("memory_id", sa.BigInteger(), nullable=False),
        sa.Column("campaign_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["memory_id"], ["agent_memories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("memory_id", "campaign_id"),
    )
    op.create_index(
        "ix_memory_campaigns_campaign",
        "memory_campaigns",
        ["campaign_id"],
        unique=False,
    )
    op.create_table(
        "agent_context_checkpoints",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("session_id", sa.BigInteger(), nullable=False),
        sa.Column("compacted_through_turn_id", sa.BigInteger(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidation_reason", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["compacted_through_turn_id", "session_id"],
            ["agent_turns.id", "agent_turns.session_id"],
            name="fk_checkpoints_turn_session",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_checkpoints_session_created",
        "agent_context_checkpoints",
        ["session_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_checkpoints_session_through",
        "agent_context_checkpoints",
        ["session_id", "compacted_through_turn_id"],
        unique=False,
    )
    op.create_index(
        "uq_checkpoints_active_boundary",
        "agent_context_checkpoints",
        ["session_id", "compacted_through_turn_id"],
        unique=True,
        postgresql_where=sa.text("invalidated_at IS NULL"),
    )
    op.create_table(
        "api_idempotency_requests",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("marketer_id", sa.BigInteger(), nullable=False),
        sa.Column("session_id", sa.BigInteger(), nullable=False),
        sa.Column("agent_turn_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "operation",
            postgresql.ENUM(name="api_operation", create_type=False),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.UUID(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="api_idempotency_status", create_type=False),
            server_default="processing",
            nullable=False,
        ),
        sa.Column("execution_token", sa.UUID(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("external_effect_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("http_status", sa.SmallInteger(), nullable=True),
        sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(status = 'processing' AND http_status IS NULL AND response_body IS NULL AND completed_at IS NULL) OR (status <> 'processing' AND http_status IS NOT NULL AND response_body IS NOT NULL AND completed_at IS NOT NULL)",
            name="ck_air_response_fields",
        ),
        sa.CheckConstraint(
            "external_result IS NULL OR (operation = 'publish_x_post' AND external_effect_started_at IS NOT NULL)",
            name="ck_air_external_result",
        ),
        sa.ForeignKeyConstraint(
            ["agent_turn_id", "session_id"],
            ["agent_turns.id", "agent_turns.session_id"],
            name="fk_air_turn_session",
        ),
        sa.ForeignKeyConstraint(
            ["marketer_id"],
            ["marketers.id"],
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "marketer_id"],
            ["agent_sessions.id", "agent_sessions.marketer_id"],
            name="fk_air_session_marketer",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_turn_id"),
        sa.UniqueConstraint(
            "marketer_id", "operation", "idempotency_key", name="uq_air_marketer_op_key"
        ),
    )
    op.create_index(
        "ix_air_marketer_op_hash",
        "api_idempotency_requests",
        ["marketer_id", "operation", "request_hash"],
        unique=False,
    )
    op.create_index(
        "ix_air_session_created",
        "api_idempotency_requests",
        ["session_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_air_status_lease",
        "api_idempotency_requests",
        ["status", "lease_expires_at"],
        unique=False,
    )
    op.create_table(
        "llm_calls",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("agent_turn_id", sa.BigInteger(), nullable=False),
        sa.Column("orcarouter_request_id", sa.String(length=255), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column("response_time_ms", sa.Integer(), nullable=True),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "called_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(input_tokens IS NULL OR input_tokens >= 0) AND (output_tokens IS NULL OR output_tokens >= 0) AND (cost_usd IS NULL OR cost_usd >= 0) AND (response_time_ms IS NULL OR response_time_ms >= 0)",
            name="ck_llm_calls_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["agent_turn_id"],
            ["agent_turns.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "agent_turn_id", name="uq_llm_calls_id_turn"),
        sa.UniqueConstraint("orcarouter_request_id"),
    )
    op.create_index(
        "ix_llm_calls_turn_called",
        "llm_calls",
        ["agent_turn_id", "called_at"],
        unique=False,
    )
    op.create_table(
        "agent_items",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("agent_turn_id", sa.BigInteger(), nullable=False),
        sa.Column("related_tool_call_item_id", sa.BigInteger(), nullable=True),
        sa.Column("llm_call_id", sa.BigInteger(), nullable=True),
        sa.Column("item_number", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column(
            "item_type",
            postgresql.ENUM(name="agent_item_type", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "context_class",
            postgresql.ENUM(name="agent_context_class", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "content_source",
            postgresql.ENUM(name="agent_content_source", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "context_status",
            postgresql.ENUM(name="agent_item_context_status", create_type=False),
            server_default="active",
            nullable=False,
        ),
        sa.Column("quarantine_reason", sa.String(length=100), nullable=True),
        sa.Column("context_override", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("quarantined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(context_status = 'quarantined' AND quarantine_reason IS NOT NULL AND context_override IS NOT NULL AND quarantined_at IS NOT NULL) OR (context_status = 'active' AND quarantine_reason IS NULL AND context_override IS NULL AND quarantined_at IS NULL)",
            name="ck_agent_items_quarantine",
        ),
        sa.CheckConstraint(
            "(item_type = 'tool_result') = (related_tool_call_item_id IS NOT NULL)",
            name="ck_agent_items_tool_result_ref",
        ),
        sa.CheckConstraint("item_number >= 1", name="ck_agent_items_number"),
        sa.ForeignKeyConstraint(
            ["agent_turn_id"],
            ["agent_turns.id"],
        ),
        sa.ForeignKeyConstraint(
            ["llm_call_id", "agent_turn_id"],
            ["llm_calls.id", "llm_calls.agent_turn_id"],
            name="fk_agent_items_llm_call",
        ),
        sa.ForeignKeyConstraint(
            ["related_tool_call_item_id", "agent_turn_id"],
            ["agent_items.id", "agent_items.agent_turn_id"],
            name="fk_agent_items_related",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_turn_id", "idempotency_key", name="uq_agent_items_turn_key"),
        sa.UniqueConstraint("agent_turn_id", "item_number", name="uq_agent_items_turn_number"),
        sa.UniqueConstraint("id", "agent_turn_id", name="uq_agent_items_id_turn"),
        sa.UniqueConstraint(
            "related_tool_call_item_id", "item_type", name="uq_agent_items_related_type"
        ),
    )
    op.create_index("ix_agent_items_llm_call", "agent_items", ["llm_call_id"], unique=False)
    op.create_table(
        "posts",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column("created_by_marketer_id", sa.BigInteger(), nullable=False),
        sa.Column("campaign_id", sa.BigInteger(), nullable=False),
        sa.Column("api_idempotency_request_id", sa.BigInteger(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("x_post_id", sa.String(length=255), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["api_idempotency_request_id"],
            ["api_idempotency_requests.id"],
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
        ),
        sa.ForeignKeyConstraint(
            ["created_by_marketer_id"],
            ["marketers.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("api_idempotency_request_id"),
        sa.UniqueConstraint("x_post_id"),
    )
    op.create_index(
        "ix_posts_company_published",
        "posts",
        ["company_id", "published_at"],
        unique=False,
    )
    op.create_table(
        "memory_posts",
        sa.Column("memory_id", sa.BigInteger(), nullable=False),
        sa.Column("post_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["memory_id"], ["agent_memories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("memory_id", "post_id"),
    )
    op.create_index("ix_memory_posts_post", "memory_posts", ["post_id"], unique=False)
    op.create_table(
        "post_embeddings",
        sa.Column("post_id", sa.BigInteger(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=1536), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("post_id"),
    )
    op.create_index("ix_post_embeddings_hash", "post_embeddings", ["content_hash"], unique=False)
    op.create_index(
        "ix_post_embeddings_hnsw",
        "post_embeddings",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_table(
        "post_metrics",
        sa.Column("post_id", sa.BigInteger(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="post_metric_status", create_type=False),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("x_pv_count", sa.BigInteger(), nullable=True),
        sa.Column("landing_user_count", sa.BigInteger(), nullable=True),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status <> 'completed' OR (x_pv_count IS NOT NULL AND landing_user_count IS NOT NULL AND measured_at IS NOT NULL)",
            name="ck_post_metrics_completed",
        ),
        sa.CheckConstraint(
            "(x_pv_count IS NULL OR x_pv_count >= 0) AND (landing_user_count IS NULL OR landing_user_count >= 0)",
            name="ck_post_metrics_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["post_id"],
            ["posts.id"],
        ),
        sa.PrimaryKeyConstraint("post_id"),
    )
    op.create_index(
        "ix_post_metrics_status_scheduled",
        "post_metrics",
        ["status", "scheduled_at"],
        unique=False,
    )
    op.create_table(
        "post_tracking_links",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("post_id", sa.BigInteger(), nullable=False),
        sa.Column("landing_url", sa.Text(), nullable=False),
        sa.Column("utm_source", sa.String(length=255), server_default="x", nullable=False),
        sa.Column("utm_medium", sa.String(length=255), server_default="social", nullable=False),
        sa.Column("utm_campaign", sa.String(length=255), nullable=False),
        sa.Column("utm_content", sa.String(length=255), nullable=False),
        sa.Column("tracked_url", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("post_id"),
        sa.UniqueConstraint(
            "utm_source",
            "utm_medium",
            "utm_campaign",
            "utm_content",
            name="uq_tracking_utm",
        ),
    )
    op.create_table(
        "security_events",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("agent_turn_id", sa.BigInteger(), nullable=False),
        sa.Column("agent_item_id", sa.BigInteger(), nullable=True),
        sa.Column("llm_call_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "event_type",
            postgresql.ENUM(name="security_event_type", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "detector",
            postgresql.ENUM(name="security_detector", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "source",
            postgresql.ENUM(name="agent_content_source", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "enforcement",
            postgresql.ENUM(name="security_enforcement", create_type=False),
            nullable=False,
        ),
        sa.Column("external_event_id", sa.String(length=255), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["agent_item_id", "agent_turn_id"],
            ["agent_items.id", "agent_items.agent_turn_id"],
            name="fk_security_events_item_turn",
        ),
        sa.ForeignKeyConstraint(
            ["agent_turn_id"],
            ["agent_turns.id"],
        ),
        sa.ForeignKeyConstraint(
            ["llm_call_id", "agent_turn_id"],
            ["llm_calls.id", "llm_calls.agent_turn_id"],
            name="fk_security_events_llm_turn",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("detector", "external_event_id", name="uq_security_events_external"),
    )
    op.create_index("ix_security_events_item", "security_events", ["agent_item_id"], unique=False)
    op.create_index("ix_security_events_llm_call", "security_events", ["llm_call_id"], unique=False)
    op.create_index("ix_security_events_turn", "security_events", ["agent_turn_id"], unique=False)
    op.create_index(
        "ix_security_events_type_detected",
        "security_events",
        ["event_type", "detected_at"],
        unique=False,
    )
    op.create_table(
        "tool_executions",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("tool_call_item_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="tool_execution_status", create_type=False),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("attempt_count >= 0", name="ck_tool_executions_attempt"),
        sa.ForeignKeyConstraint(
            ["tool_call_item_id"],
            ["agent_items.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tool_call_item_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    op.drop_table("tool_executions")
    op.drop_index("ix_security_events_type_detected", table_name="security_events")
    op.drop_index("ix_security_events_turn", table_name="security_events")
    op.drop_index("ix_security_events_llm_call", table_name="security_events")
    op.drop_index("ix_security_events_item", table_name="security_events")
    op.drop_table("security_events")
    op.drop_table("post_tracking_links")
    op.drop_index("ix_post_metrics_status_scheduled", table_name="post_metrics")
    op.drop_table("post_metrics")
    op.drop_index(
        "ix_post_embeddings_hnsw",
        table_name="post_embeddings",
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_index("ix_post_embeddings_hash", table_name="post_embeddings")
    op.drop_table("post_embeddings")
    op.drop_index("ix_memory_posts_post", table_name="memory_posts")
    op.drop_table("memory_posts")
    op.drop_index("ix_posts_company_published", table_name="posts")
    op.drop_table("posts")
    op.drop_index("ix_agent_items_llm_call", table_name="agent_items")
    op.drop_table("agent_items")
    op.drop_index("ix_llm_calls_turn_called", table_name="llm_calls")
    op.drop_table("llm_calls")
    op.drop_index("ix_air_status_lease", table_name="api_idempotency_requests")
    op.drop_index("ix_air_session_created", table_name="api_idempotency_requests")
    op.drop_index("ix_air_marketer_op_hash", table_name="api_idempotency_requests")
    op.drop_table("api_idempotency_requests")
    op.drop_index(
        "uq_checkpoints_active_boundary",
        table_name="agent_context_checkpoints",
        postgresql_where=sa.text("invalidated_at IS NULL"),
    )
    op.drop_index("ix_checkpoints_session_through", table_name="agent_context_checkpoints")
    op.drop_index("ix_checkpoints_session_created", table_name="agent_context_checkpoints")
    op.drop_table("agent_context_checkpoints")
    op.drop_index("ix_memory_campaigns_campaign", table_name="memory_campaigns")
    op.drop_table("memory_campaigns")
    op.drop_index(
        "ix_campaign_embeddings_hnsw",
        table_name="campaign_embeddings",
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_index("ix_campaign_embeddings_hash", table_name="campaign_embeddings")
    op.drop_table("campaign_embeddings")
    op.drop_index("ix_agent_turns_status_created", table_name="agent_turns")
    op.drop_index("ix_agent_turns_session_created", table_name="agent_turns")
    op.drop_table("agent_turns")
    op.drop_index("ix_campaigns_company_created", table_name="campaigns")
    op.drop_table("campaigns")
    op.drop_index("ix_agent_sessions_parent_created", table_name="agent_sessions")
    op.drop_index("ix_agent_sessions_marketer_updated", table_name="agent_sessions")
    op.drop_table("agent_sessions")
    op.drop_table("marketers")
    op.drop_index(
        "ix_agent_memories_hnsw",
        table_name="agent_memories",
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_index("ix_agent_memories_company", table_name="agent_memories")
    op.drop_table("agent_memories")
    op.drop_table("users")
    op.drop_table("companies")
    postgresql.ENUM(name="tool_execution_status").drop(bind)
    postgresql.ENUM(name="security_enforcement").drop(bind)
    postgresql.ENUM(name="security_detector").drop(bind)
    postgresql.ENUM(name="security_event_type").drop(bind)
    postgresql.ENUM(name="post_metric_status").drop(bind)
    postgresql.ENUM(name="agent_item_context_status").drop(bind)
    postgresql.ENUM(name="agent_content_source").drop(bind)
    postgresql.ENUM(name="agent_context_class").drop(bind)
    postgresql.ENUM(name="agent_item_type").drop(bind)
    postgresql.ENUM(name="api_idempotency_status").drop(bind)
    postgresql.ENUM(name="api_operation").drop(bind)
    postgresql.ENUM(name="agent_turn_status").drop(bind)
    postgresql.ENUM(name="agent_type").drop(bind)
