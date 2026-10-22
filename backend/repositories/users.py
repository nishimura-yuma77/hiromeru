"""自社ユーザー管理と招待のRepository（API_DESIGN 11.2、11.3）。

すべての取得は会社IDで絞り込み、管理機能で他社のユーザーを参照・変更しない。
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from domain.enums import EmailStatus, UserStatus
from models import Admin, Company, Email, Invitation, User

INVITATION_TTL = timedelta(hours=1)

type UserType = Literal["admin", "marketer"]


@dataclass(frozen=True)
class CompanyUserView:
    """管理画面へ返す自社ユーザー。パスワードハッシュ・招待トークン・会社IDは含めない。"""

    user_id: int
    name: str
    email: str
    user_type: UserType
    status: UserStatus
    is_responsible: bool
    email_status: EmailStatus | None


@dataclass(frozen=True)
class LockedUser:
    """行ロック済みの自社ユーザーと、その管理権限。"""

    user: User
    admin: Admin | None

    @property
    def user_type(self) -> UserType:
        """adminsがあれば管理ユーザー。"""
        return "admin" if self.admin is not None else "marketer"

    @property
    def is_responsible(self) -> bool:
        """会社の責任者かどうか。"""
        return self.admin is not None and self.admin.is_responsible


@dataclass(frozen=True)
class InvitationTarget:
    """招待トークンから引いた招待行と対象ユーザー。"""

    invitation: Invitation
    user: User
    user_type: UserType


def _latest_email_status():  # noqa: ANN202 - SQLAlchemyのScalar Subquery
    return (
        select(Email.status)
        .where(Email.user_id == User.id)
        .order_by(Email.created_at.desc(), Email.id.desc())
        .limit(1)
        .correlate(User)
        .scalar_subquery()
    )


class UserAdminRepository:
    """自社ユーザーの取得・変更と、招待メール送信操作・招待リンクの記録。"""

    def __init__(self, session: AsyncSession) -> None:
        """セッションを受け取る。"""
        self._session = session

    async def count_company_users(self, company_id: int) -> int:
        """招待中を含む自社ユーザーの件数を返す。"""
        stmt = select(func.count()).select_from(User).where(User.company_id == company_id)
        return int(await self._session.scalar(stmt) or 0)

    async def list_company_users(
        self, company_id: int, *, offset: int, limit: int, user_id: int | None = None
    ) -> list[CompanyUserView]:
        """自社ユーザーを登録日時の新しい順（同じ日時はID順）で返す。"""
        stmt = (
            select(
                User.id,
                User.name,
                User.email,
                Admin.id,
                User.status,
                Admin.is_responsible,
                _latest_email_status(),
            )
            .outerjoin(Admin, Admin.user_id == User.id)
            .where(User.company_id == company_id)
            .order_by(User.created_at.desc(), User.id.desc())
            .offset(offset)
            .limit(limit)
        )
        if user_id is not None:
            stmt = stmt.where(User.id == user_id)
        rows = (await self._session.execute(stmt)).all()
        return [
            CompanyUserView(
                user_id=row[0],
                name=row[1],
                email=row[2],
                user_type="admin" if row[3] is not None else "marketer",
                status=row[4],
                is_responsible=bool(row[5]),
                email_status=row[6],
            )
            for row in rows
        ]

    async def get_company_user(self, company_id: int, user_id: int) -> CompanyUserView | None:
        """自社ユーザーを1件返す。他社・存在しない場合は None。"""
        rows = await self.list_company_users(company_id, offset=0, limit=1, user_id=user_id)
        return rows[0] if rows else None

    async def lock_company_user(self, company_id: int, user_id: int) -> LockedUser | None:
        """自社ユーザーの行をロックして取得する。他社・存在しない場合は None。"""
        user = (
            await self._session.execute(
                select(User)
                .where(User.id == user_id, User.company_id == company_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if user is None:
            return None
        admin = (
            await self._session.execute(select(Admin).where(Admin.user_id == user_id))
        ).scalar_one_or_none()
        return LockedUser(user, admin)

    async def email_exists(self, email: str) -> bool:
        """正規化済みメールアドレスが全社のいずれかで使われているかを返す。"""
        stmt = select(User.id).where(User.email == email)
        return (await self._session.execute(stmt)).first() is not None

    async def company_name(self, company_id: int) -> str:
        """招待メールに載せる会社名を返す。"""
        return str(await self._session.scalar(select(Company.name).where(Company.id == company_id)))

    async def create_invited_user(
        self, *, company_id: int, name: str, email: str, user_type: UserType, now: datetime
    ) -> User:
        """パスワード未設定の招待中ユーザーを作る。管理ユーザーならadminsも作る。"""
        user = User(
            company_id=company_id,
            name=name,
            email=email,
            password=None,
            status=UserStatus.INVITED,
            auth_generation=0,
            created_at=now,
            updated_at=now,
        )
        self._session.add(user)
        await self._session.flush()
        if user_type == "admin":
            await self.add_admin(user.id, company_id, now)
        return user

    async def add_admin(self, user_id: int, company_id: int, now: datetime) -> None:
        """管理権限を追加する。責任者にはしない。"""
        self._session.add(
            Admin(
                user_id=user_id,
                company_id=company_id,
                is_responsible=False,
                created_at=now,
                updated_at=now,
            )
        )
        await self._session.flush()

    async def remove_admin(self, user_id: int) -> None:
        """管理権限を削除する。責任者の削除は呼び出し側で禁止する。"""
        await self._session.execute(
            delete(Admin).where(Admin.user_id == user_id, Admin.is_responsible.is_(False))
        )

    async def invalidate_open_invitations(self, user_id: int, now: datetime) -> None:
        """未使用・未無効化の招待リンクを無効化する。期限切れのリンクも明示的に無効化する。"""
        await self._session.execute(
            update(Invitation)
            .where(
                Invitation.user_id == user_id,
                Invitation.used_at.is_(None),
                Invitation.invalidated_at.is_(None),
            )
            .values(invalidated_at=now)
        )

    async def create_send(self, *, user_id: int, token_hash: str, now: datetime) -> int:
        """送信操作と招待リンクを登録し、送信操作IDを返す。リンクは発行から1時間有効。"""
        email = Email(
            user_id=user_id,
            status=EmailStatus.PENDING,
            attempt_count=0,
            created_at=now,
            updated_at=now,
        )
        self._session.add(email)
        await self._session.flush()
        self._session.add(
            Invitation(
                user_id=user_id,
                email_id=email.id,
                token_hash=token_hash,
                expires_at=now + INVITATION_TTL,
                created_at=now,
            )
        )
        await self._session.flush()
        return email.id

    async def record_send_result(
        self,
        email_id: int,
        *,
        status: EmailStatus,
        attempt_count: int,
        ses_message_id: str | None,
        error_code: str | None,
        now: datetime,
    ) -> None:
        """送信操作の結果を記録する。pendingの行だけを更新する。"""
        await self._session.execute(
            update(Email)
            .where(Email.id == email_id, Email.status == EmailStatus.PENDING)
            .values(
                status=status,
                attempt_count=attempt_count,
                ses_message_id=ses_message_id,
                last_error_code=error_code,
                updated_at=now,
            )
        )

    async def find_invitation(
        self, token_hash: str, *, lock: bool = False
    ) -> InvitationTarget | None:
        """招待トークンのハッシュから招待行と対象ユーザーを取得する。"""
        stmt = (
            select(Invitation, User, Admin.id)
            .join(User, User.id == Invitation.user_id)
            .outerjoin(Admin, Admin.user_id == User.id)
            .where(Invitation.token_hash == token_hash)
        )
        if lock:
            stmt = stmt.with_for_update(of=(Invitation, User))
        row = (await self._session.execute(stmt)).one_or_none()
        if row is None:
            return None
        return InvitationTarget(row[0], row[1], "admin" if row[2] is not None else "marketer")
