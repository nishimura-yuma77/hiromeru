"""会社・ユーザーと、管理権限・招待のモデル。"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from domain.enums import EmailStatus, UserStatus
from models.base import Base, created_at_column, pg_enum, updated_at_column


class Company(Base):
    """業務データの所有主体。"""

    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class User(Base):
    """認証主体かつ業務操作・会話履歴の主体。1人のユーザーは1社だけに所属する。"""

    __tablename__ = "users"
    __table_args__ = (
        # 業務データ・adminsからの複合外部キーで、作成者と会社の一致をDBで保証する。
        UniqueConstraint("id", "company_id", name="uq_users_id_company"),
        Index("ix_users_company", "company_id"),
        CheckConstraint(
            "(status = 'active' AND password IS NOT NULL)"
            " OR (status IN ('invited', 'suspended') AND password IS NULL)",
            name="users_status_password_check",
        ),
        CheckConstraint("auth_generation >= 0", name="users_auth_generation_check"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # 作成時に確定し、変更しない。
    company_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("companies.id"))
    name: Mapped[str] = mapped_column(String(255))
    # 前後の空白を除き小文字化してから保存する。全社で一意。
    email: Mapped[str] = mapped_column(String(255), unique=True)
    # argon2でハッシュ化した値。invited・suspendedではNULL。平文は保存しない。
    password: Mapped[str | None] = mapped_column(String(255), default=None)
    status: Mapped[UserStatus] = mapped_column(
        pg_enum(UserStatus, "user_status"), server_default="invited"
    )
    # 停止・再開・実際の種別変更で更新し、変更前のCookieを失効させる。
    auth_generation: Mapped[int] = mapped_column(BigInteger, server_default="0")
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class Admin(Base):
    """自社ユーザーの管理権限。存在すれば管理ユーザーとする。"""

    __tablename__ = "admins"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "company_id"],
            ["users.id", "users.company_id"],
            name="fk_admins_user_company",
        ),
        Index("ix_admins_company", "company_id"),
        # 責任者は会社ごとに最大1人。最低1人は登録手順と操作禁止で維持する。
        Index(
            "uq_admins_responsible_company",
            "company_id",
            unique=True,
            postgresql_where=text("is_responsible"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    company_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("companies.id"))
    is_responsible: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class Email(Base):
    """招待メールの1回の送信操作。自動再試行は同じ行で数える。"""

    __tablename__ = "emails"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_emails_id_user"),
        Index("ix_emails_user_created", "user_id", "created_at"),
        CheckConstraint("attempt_count BETWEEN 0 AND 3", name="emails_attempt_count_check"),
        CheckConstraint(
            "(status = 'pending' AND ses_message_id IS NULL AND last_error_code IS NULL)"
            " OR (status = 'accepted' AND ses_message_id IS NOT NULL"
            " AND last_error_code IS NULL)"
            " OR (status IN ('failed', 'outcome_unknown') AND ses_message_id IS NULL"
            " AND last_error_code IS NOT NULL)",
            name="emails_status_result_check",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    status: Mapped[EmailStatus] = mapped_column(
        pg_enum(EmailStatus, "email_status"), server_default="pending"
    )
    attempt_count: Mapped[int] = mapped_column(Integer, server_default="0")
    ses_message_id: Mapped[str | None] = mapped_column(String(255), default=None)
    last_error_code: Mapped[str | None] = mapped_column(String(100), default=None)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class Invitation(Base):
    """招待リンク。トークンはハッシュだけを保存する。"""

    __tablename__ = "invitations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["email_id", "user_id"],
            ["emails.id", "emails.user_id"],
            name="fk_invitations_email_user",
        ),
        Index("ix_invitations_user_created", "user_id", "created_at"),
        # 1人のユーザーに未使用・未無効化の招待リンクは最大1件。
        Index(
            "uq_invitations_open_user",
            "user_id",
            unique=True,
            postgresql_where=text("used_at IS NULL AND invalidated_at IS NULL"),
        ),
        CheckConstraint(
            "used_at IS NULL OR invalidated_at IS NULL",
            name="invitations_used_or_invalidated_check",
        ),
        CheckConstraint(
            "expires_at = created_at + interval '1 hour'", name="invitations_expiry_check"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    email_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    token_hash: Mapped[str] = mapped_column(String(255), unique=True)
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None] = mapped_column(default=None)
    invalidated_at: Mapped[datetime | None] = mapped_column(default=None)
    # トークン発行日時。SES送信前の招待行登録時に設定する。
    created_at: Mapped[datetime]
