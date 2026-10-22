"""absorb marketers into users and add user management tables

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-21

marketersを廃止して表示名と所属会社をusersへ統合し、業務操作主体・作成者・会話履歴の
所有者をusers.idで表す（DATABASE.dbml、USER_ID_MIGRATION.md）。あわせて、Issue #58の
管理権限（admins）、招待メール送信操作（emails）、招待リンク（invitations）を追加する。

ローンチ前のDBは初期化して再投入する方針だが、開発DBを壊さないよう既存行は
marketers.user_idへ変換する。既存ユーザーはパスワードを持つため active とする。
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_USER_STATUS = ("invited", "active", "suspended")
_EMAIL_STATUS = ("pending", "accepted", "failed", "outcome_unknown")

# (テーブル, 旧列, 新列)。値はmarketers.idからmarketers.user_idへ変換する。
_OWNER_COLUMNS = (
    ("agent_sessions", "marketer_id", "user_id"),
    ("api_idempotency_requests", "marketer_id", "user_id"),
    ("api_list_snapshots", "marketer_id", "user_id"),
    ("campaigns", "created_by_marketer_id", "created_by_user_id"),
    ("posts", "created_by_marketer_id", "created_by_user_id"),
)


def _timestamps() -> list[sa.Column[datetime]]:
    return [
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
    ]


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(*_USER_STATUS, name="user_status").create(bind)
    postgresql.ENUM(*_EMAIL_STATUS, name="email_status").create(bind)
    user_status = postgresql.ENUM(*_USER_STATUS, name="user_status", create_type=False)
    email_status = postgresql.ENUM(*_EMAIL_STATUS, name="email_status", create_type=False)

    # users: 所属会社・表示名・利用状態・認証世代を追加し、marketersから埋める。
    op.add_column("users", sa.Column("company_id", sa.BigInteger(), nullable=True))
    op.add_column("users", sa.Column("name", sa.String(length=255), nullable=True))
    op.add_column(
        "users", sa.Column("status", user_status, server_default="active", nullable=False)
    )
    op.add_column(
        "users",
        sa.Column("auth_generation", sa.BigInteger(), server_default="0", nullable=False),
    )
    op.execute(
        "UPDATE users SET company_id = m.company_id, name = m.name, email = lower(trim(email)) "
        "FROM marketers m WHERE m.user_id = users.id"
    )
    op.alter_column("users", "company_id", nullable=False)
    op.alter_column("users", "name", nullable=False)
    op.alter_column("users", "status", server_default="invited")
    op.alter_column("users", "password", existing_type=sa.String(length=255), nullable=True)
    op.create_foreign_key("users_company_id_fkey", "users", "companies", ["company_id"], ["id"])
    op.create_unique_constraint("uq_users_id_company", "users", ["id", "company_id"])
    op.create_index("ix_users_company", "users", ["company_id"], unique=False)
    op.create_check_constraint(
        "users_status_password_check",
        "users",
        "(status = 'active' AND password IS NOT NULL)"
        " OR (status IN ('invited', 'suspended') AND password IS NULL)",
    )
    op.create_check_constraint("users_auth_generation_check", "users", "auth_generation >= 0")

    # 旧marketers参照の制約・索引を外してから、列名と値をuser_idへ変える。
    op.drop_constraint("fk_air_session_marketer", "api_idempotency_requests", type_="foreignkey")
    op.drop_constraint("fk_agent_sessions_parent", "agent_sessions", type_="foreignkey")
    op.drop_constraint("uq_air_marketer_op_key", "api_idempotency_requests", type_="unique")
    op.drop_constraint("uq_agent_sessions_id_marketer", "agent_sessions", type_="unique")
    op.drop_index("ix_air_marketer_op_hash", table_name="api_idempotency_requests")
    op.drop_index("ix_agent_sessions_marketer_updated", table_name="agent_sessions")
    op.drop_index("ix_api_list_snapshots_owner_resource_expiry", table_name="api_list_snapshots")
    for table, old, new in _OWNER_COLUMNS:
        op.drop_constraint(f"{table}_{old}_fkey", table, type_="foreignkey")
        op.alter_column(table, old, new_column_name=new)
        op.execute(
            f"UPDATE {table} SET {new} = m.user_id FROM marketers m "  # noqa: S608 - 固定の識別子
            f"WHERE m.id = {table}.{new}"
        )

    op.create_foreign_key(
        "agent_sessions_user_id_fkey", "agent_sessions", "users", ["user_id"], ["id"]
    )
    op.create_unique_constraint("uq_agent_sessions_id_user", "agent_sessions", ["id", "user_id"])
    op.create_foreign_key(
        "fk_agent_sessions_parent",
        "agent_sessions",
        "agent_sessions",
        ["parent_session_id", "user_id"],
        ["id", "user_id"],
    )
    op.create_index(
        "ix_agent_sessions_user_updated", "agent_sessions", ["user_id", "updated_at"], unique=False
    )
    op.create_foreign_key(
        "api_idempotency_requests_user_id_fkey",
        "api_idempotency_requests",
        "users",
        ["user_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_air_user_op_key",
        "api_idempotency_requests",
        ["user_id", "operation", "idempotency_key"],
    )
    op.create_foreign_key(
        "fk_air_session_user",
        "api_idempotency_requests",
        "agent_sessions",
        ["session_id", "user_id"],
        ["id", "user_id"],
    )
    op.create_index(
        "ix_air_user_op_hash",
        "api_idempotency_requests",
        ["user_id", "operation", "request_hash"],
        unique=False,
    )
    op.create_foreign_key(
        "api_list_snapshots_user_id_fkey",
        "api_list_snapshots",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_api_list_snapshots_owner_resource_expiry",
        "api_list_snapshots",
        ["user_id", "resource", "expires_at"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_campaigns_creator_company",
        "campaigns",
        "users",
        ["created_by_user_id", "company_id"],
        ["id", "company_id"],
    )
    op.create_foreign_key(
        "fk_posts_creator_company",
        "posts",
        "users",
        ["created_by_user_id", "company_id"],
        ["id", "company_id"],
    )

    op.drop_table("marketers")

    op.create_table(
        "admins",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column("is_responsible", sa.Boolean(), server_default="false", nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(
            ["user_id", "company_id"],
            ["users.id", "users.company_id"],
            name="fk_admins_user_company",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_admins_company", "admins", ["company_id"], unique=False)
    op.create_index(
        "uq_admins_responsible_company",
        "admins",
        ["company_id"],
        unique=True,
        postgresql_where=sa.text("is_responsible"),
    )
    op.create_table(
        "emails",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("status", email_status, server_default="pending", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("ses_message_id", sa.String(length=255), nullable=True),
        sa.Column("last_error_code", sa.String(length=100), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("attempt_count BETWEEN 0 AND 3", name="emails_attempt_count_check"),
        sa.CheckConstraint(
            "(status = 'pending' AND ses_message_id IS NULL AND last_error_code IS NULL)"
            " OR (status = 'accepted' AND ses_message_id IS NOT NULL"
            " AND last_error_code IS NULL)"
            " OR (status IN ('failed', 'outcome_unknown') AND ses_message_id IS NULL"
            " AND last_error_code IS NOT NULL)",
            name="emails_status_result_check",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "user_id", name="uq_emails_id_user"),
    )
    op.create_index("ix_emails_user_created", "emails", ["user_id", "created_at"], unique=False)
    op.create_table(
        "invitations",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("email_id", sa.BigInteger(), nullable=False),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "used_at IS NULL OR invalidated_at IS NULL",
            name="invitations_used_or_invalidated_check",
        ),
        sa.CheckConstraint(
            "expires_at = created_at + interval '1 hour'", name="invitations_expiry_check"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["email_id", "user_id"],
            ["emails.id", "emails.user_id"],
            name="fk_invitations_email_user",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email_id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "ix_invitations_user_created", "invitations", ["user_id", "created_at"], unique=False
    )
    op.create_index(
        "uq_invitations_open_user",
        "invitations",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("used_at IS NULL AND invalidated_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("invitations")
    op.drop_table("emails")
    op.drop_table("admins")

    # users 1件ごとにmarketersを作り直す。旧スキーマは1社1マーケターのため、
    # 同じ会社の2人目以降のユーザーがいる場合はダウングレードできない。
    op.create_table(
        "marketers",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id"),
        sa.UniqueConstraint("user_id"),
    )
    op.execute(
        "INSERT INTO marketers (id, user_id, name, company_id, created_at, updated_at) "
        "SELECT id, id, name, company_id, created_at, updated_at FROM users"
    )
    op.execute(
        "SELECT setval(pg_get_serial_sequence('marketers', 'id'), "
        "(SELECT coalesce(max(id), 0) + 1 FROM marketers), false)"
    )

    op.drop_constraint("fk_posts_creator_company", "posts", type_="foreignkey")
    op.drop_constraint("fk_campaigns_creator_company", "campaigns", type_="foreignkey")
    op.drop_index("ix_api_list_snapshots_owner_resource_expiry", table_name="api_list_snapshots")
    op.drop_constraint("api_list_snapshots_user_id_fkey", "api_list_snapshots", type_="foreignkey")
    op.drop_index("ix_air_user_op_hash", table_name="api_idempotency_requests")
    op.drop_constraint("fk_air_session_user", "api_idempotency_requests", type_="foreignkey")
    op.drop_constraint("uq_air_user_op_key", "api_idempotency_requests", type_="unique")
    op.drop_constraint(
        "api_idempotency_requests_user_id_fkey", "api_idempotency_requests", type_="foreignkey"
    )
    op.drop_index("ix_agent_sessions_user_updated", table_name="agent_sessions")
    op.drop_constraint("fk_agent_sessions_parent", "agent_sessions", type_="foreignkey")
    op.drop_constraint("uq_agent_sessions_id_user", "agent_sessions", type_="unique")
    op.drop_constraint("agent_sessions_user_id_fkey", "agent_sessions", type_="foreignkey")

    # marketers.id は users.id と同じ値で作り直したため、値の変換は不要。
    for table, old, new in _OWNER_COLUMNS:
        op.alter_column(table, new, new_column_name=old)
        ondelete = "CASCADE" if table == "api_list_snapshots" else None
        op.create_foreign_key(
            f"{table}_{old}_fkey", table, "marketers", [old], ["id"], ondelete=ondelete
        )
    op.create_unique_constraint(
        "uq_agent_sessions_id_marketer", "agent_sessions", ["id", "marketer_id"]
    )
    op.create_foreign_key(
        "fk_agent_sessions_parent",
        "agent_sessions",
        "agent_sessions",
        ["parent_session_id", "marketer_id"],
        ["id", "marketer_id"],
    )
    op.create_index(
        "ix_agent_sessions_marketer_updated",
        "agent_sessions",
        ["marketer_id", "updated_at"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_air_marketer_op_key",
        "api_idempotency_requests",
        ["marketer_id", "operation", "idempotency_key"],
    )
    op.create_foreign_key(
        "fk_air_session_marketer",
        "api_idempotency_requests",
        "agent_sessions",
        ["session_id", "marketer_id"],
        ["id", "marketer_id"],
    )
    op.create_index(
        "ix_air_marketer_op_hash",
        "api_idempotency_requests",
        ["marketer_id", "operation", "request_hash"],
        unique=False,
    )
    op.create_index(
        "ix_api_list_snapshots_owner_resource_expiry",
        "api_list_snapshots",
        ["marketer_id", "resource", "expires_at"],
        unique=False,
    )

    op.drop_constraint("users_auth_generation_check", "users", type_="check")
    op.drop_constraint("users_status_password_check", "users", type_="check")
    op.drop_index("ix_users_company", table_name="users")
    op.drop_constraint("uq_users_id_company", "users", type_="unique")
    op.drop_constraint("users_company_id_fkey", "users", type_="foreignkey")
    # 招待中・停止中のユーザーはパスワードを持たない。argon2のハッシュとして解釈できない値を
    # 入れ、旧スキーマのNOT NULLへ戻してもログインできないようにする。
    op.execute("UPDATE users SET password = '!' WHERE password IS NULL")
    op.alter_column("users", "password", existing_type=sa.String(length=255), nullable=False)
    op.drop_column("users", "auth_generation")
    op.drop_column("users", "status")
    op.drop_column("users", "name")
    op.drop_column("users", "company_id")
    postgresql.ENUM(name="email_status").drop(op.get_bind())
    postgresql.ENUM(name="user_status").drop(op.get_bind())
