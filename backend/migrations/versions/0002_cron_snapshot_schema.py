"""add cron state and list snapshots

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add Cron execution state and stable list snapshots without replacing existing data."""
    op.add_column("post_metrics", sa.Column("execution_token", sa.UUID(), nullable=True))
    op.add_column(
        "post_metrics", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "post_metrics",
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=True),
    )
    op.add_column(
        "post_metrics", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "post_metrics", sa.Column("last_error_code", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "post_metrics", sa.Column("memory_generated_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "post_metrics", sa.Column("memory_failed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "post_metrics",
        sa.Column("memory_attempt_count", sa.Integer(), server_default="0", nullable=True),
    )
    op.add_column(
        "post_metrics",
        sa.Column("memory_next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "post_metrics", sa.Column("memory_last_error_code", sa.String(length=255), nullable=True)
    )

    # Make the existing-row backfill explicit before enforcing NOT NULL.
    op.execute(
        "UPDATE post_metrics SET attempt_count = 0, memory_attempt_count = 0 "
        "WHERE attempt_count IS NULL OR memory_attempt_count IS NULL"
    )
    op.alter_column("post_metrics", "attempt_count", nullable=False)
    op.alter_column("post_metrics", "memory_attempt_count", nullable=False)
    op.create_check_constraint(
        "ck_post_metrics_attempts_non_negative",
        "post_metrics",
        "attempt_count >= 0 AND memory_attempt_count >= 0",
    )

    op.drop_index("ix_post_metrics_status_scheduled", table_name="post_metrics")
    op.create_index(
        "ix_post_metrics_status_next_scheduled",
        "post_metrics",
        ["status", "next_attempt_at", "scheduled_at"],
        unique=False,
    )
    op.create_index(
        "ix_post_metrics_memory_retry",
        "post_metrics",
        ["memory_generated_at", "memory_failed_at", "memory_next_attempt_at"],
        unique=False,
    )

    op.drop_constraint("post_metrics_post_id_fkey", "post_metrics", type_="foreignkey")
    op.create_foreign_key(
        "post_metrics_post_id_fkey",
        "post_metrics",
        "posts",
        ["post_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "api_list_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("marketer_id", sa.BigInteger(), nullable=False),
        sa.Column("resource", sa.String(length=50), nullable=False),
        sa.Column("filter_hash", sa.String(length=64), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "resource IN ('posts', 'metrics')", name="ck_api_list_snapshots_resource"
        ),
        sa.ForeignKeyConstraint(["marketer_id"], ["marketers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_api_list_snapshots_owner_resource_expiry",
        "api_list_snapshots",
        ["marketer_id", "resource", "expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_api_list_snapshots_expiry",
        "api_list_snapshots",
        ["expires_at"],
        unique=False,
    )
    op.create_table(
        "api_list_snapshot_items",
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("item", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint("position >= 0", name="ck_api_list_snapshot_items_position"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["api_list_snapshots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("snapshot_id", "position"),
    )


def downgrade() -> None:
    """Remove this revision.

    This irreversibly deletes every list snapshot and discards Cron lease, retry,
    error, attempt-counter, and memory-generation state. Core metric values and
    their pending/completed/failed status remain intact.
    """
    op.drop_table("api_list_snapshot_items")
    op.drop_index("ix_api_list_snapshots_expiry", table_name="api_list_snapshots")
    op.drop_index("ix_api_list_snapshots_owner_resource_expiry", table_name="api_list_snapshots")
    op.drop_table("api_list_snapshots")

    op.drop_constraint("post_metrics_post_id_fkey", "post_metrics", type_="foreignkey")
    op.create_foreign_key("post_metrics_post_id_fkey", "post_metrics", "posts", ["post_id"], ["id"])
    op.drop_index("ix_post_metrics_memory_retry", table_name="post_metrics")
    op.drop_index("ix_post_metrics_status_next_scheduled", table_name="post_metrics")
    op.create_index(
        "ix_post_metrics_status_scheduled",
        "post_metrics",
        ["status", "scheduled_at"],
        unique=False,
    )
    op.drop_constraint("ck_post_metrics_attempts_non_negative", "post_metrics", type_="check")
    op.drop_column("post_metrics", "memory_last_error_code")
    op.drop_column("post_metrics", "memory_next_attempt_at")
    op.drop_column("post_metrics", "memory_attempt_count")
    op.drop_column("post_metrics", "memory_failed_at")
    op.drop_column("post_metrics", "memory_generated_at")
    op.drop_column("post_metrics", "last_error_code")
    op.drop_column("post_metrics", "next_attempt_at")
    op.drop_column("post_metrics", "attempt_count")
    op.drop_column("post_metrics", "lease_expires_at")
    op.drop_column("post_metrics", "execution_token")
