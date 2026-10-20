"""認証主体（users）と、初期設定での会社・責任者登録のRepository。"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from domain.enums import UserStatus
from models import Admin, Company, User


@dataclass(frozen=True)
class AuthUser:
    """認証済みContextの元になるユーザー情報。"""

    user_id: int
    company_id: int
    email: str
    status: UserStatus
    auth_generation: int
    is_admin: bool


def _auth_user_query() -> Select[tuple[int, int, str, UserStatus, int, int, str | None]]:
    return select(
        User.id,
        User.company_id,
        User.email,
        User.status,
        User.auth_generation,
        Admin.id,
        User.password,
    ).outerjoin(Admin, Admin.user_id == User.id)


class IdentityRepository:
    """認証主体の取得と、初期設定での登録。"""

    def __init__(self, session: AsyncSession) -> None:
        """セッションを受け取る。"""
        self._session = session

    async def find_login_target(self, email: str) -> tuple[AuthUser, str | None] | None:
        """正規化済みメールアドレスからユーザーとパスワードハッシュを取得する。"""
        row = (
            await self._session.execute(_auth_user_query().where(User.email == email))
        ).one_or_none()
        if row is None:
            return None
        return AuthUser(row[0], row[1], row[2], row[3], row[4], row[5] is not None), row[6]

    async def get_auth_user(self, user_id: int) -> AuthUser | None:
        """ユーザーIDから認証済みContextの元になる情報を取得する。"""
        row = (
            await self._session.execute(_auth_user_query().where(User.id == user_id))
        ).one_or_none()
        if row is None:
            return None
        return AuthUser(row[0], row[1], row[2], row[3], row[4], row[5] is not None)

    async def email_exists(self, email: str) -> bool:
        """正規化済みメールアドレスが全社のいずれかで使われているかを返す。"""
        stmt = select(User.id).where(User.email == email)
        return (await self._session.execute(stmt)).first() is not None

    async def create_company_with_responsible(
        self,
        *,
        company_name: str,
        name: str,
        email: str,
        password_hash: str,
        now: datetime,
    ) -> AuthUser:
        """会社・責任者ユーザー・責任者のadminsを作成する（初期設定スクリプト用）。

        責任者は招待を経ず、作成直後からログインできる active とする。
        """
        company = Company(name=company_name, created_at=now, updated_at=now)
        self._session.add(company)
        await self._session.flush()
        user = User(
            company_id=company.id,
            name=name,
            email=email,
            password=password_hash,
            status=UserStatus.ACTIVE,
            auth_generation=0,
            created_at=now,
            updated_at=now,
        )
        self._session.add(user)
        await self._session.flush()
        self._session.add(
            Admin(
                user_id=user.id,
                company_id=company.id,
                is_responsible=True,
                created_at=now,
                updated_at=now,
            )
        )
        await self._session.flush()
        return AuthUser(user.id, company.id, email, UserStatus.ACTIVE, 0, is_admin=True)
