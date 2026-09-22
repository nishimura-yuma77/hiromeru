"""add agent context checkpoint source items

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-23

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_context_checkpoint_items",
        sa.Column("checkpoint_id", sa.BigInteger(), nullable=False),
        sa.Column("item_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["checkpoint_id"], ["agent_context_checkpoints.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["item_id"], ["agent_items.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("checkpoint_id", "item_id"),
    )
    op.create_index(
        "ix_checkpoint_items_item",
        "agent_context_checkpoint_items",
        ["item_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_checkpoint_items_item", table_name="agent_context_checkpoint_items")
    op.drop_table("agent_context_checkpoint_items")
