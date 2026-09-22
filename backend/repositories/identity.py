"""ユーザー・会社・マーケターのRepository。"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Company, Marketer, User


@dataclass(frozen=True)
class MarketerRecord:
    """認証済みContextの元になるマーケター情報。"""

    marketer_id: int
    company_id: int
    user_id: int
    email: str


class IdentityRepository:
    """認証主体の取得と、初期データ投入。"""

    def __init__(self, session: AsyncSession) -> None:
        """セッションを受け取る。"""
        self._session = session

    async def find_login_target(self, email: str) -> tuple[MarketerRecord, str] | None:
        """メールアドレスからマーケターとパスワードハッシュを取得する。

        ユーザーにマーケタープロファイルがない場合は None（ログインできない）。
        """
        stmt = (
            select(Marketer.id, Marketer.company_id, User.id, User.email, User.password)
            .join(User, Marketer.user_id == User.id)
            .where(User.email == email)
        )
        row = (await self._session.execute(stmt)).one_or_none()
        if row is None:
            return None
        record = MarketerRecord(row[0], row[1], row[2], row[3])
        return record, row[4]

    async def get_marketer(self, marketer_id: int) -> MarketerRecord | None:
        """マーケターIDから認証済みContextの元になる情報を取得する。"""
        stmt = (
            select(Marketer.id, Marketer.company_id, User.id, User.email)
            .join(User, Marketer.user_id == User.id)
            .where(Marketer.id == marketer_id)
        )
        row = (await self._session.execute(stmt)).one_or_none()
        return None if row is None else MarketerRecord(row[0], row[1], row[2], row[3])

    async def create_account(
        self,
        *,
        company_name: str,
        marketer_name: str,
        email: str,
        password_hash: str,
        now: datetime,
    ) -> MarketerRecord:
        """会社・ユーザー・マーケターを作成する（初期データ投入スクリプト用）。"""
        company = Company(name=company_name, created_at=now, updated_at=now)
        user = User(email=email, password=password_hash, created_at=now, updated_at=now)
        self._session.add_all([company, user])
        await self._session.flush()
        marketer = Marketer(
            user_id=user.id,
            name=marketer_name,
            company_id=company.id,
            created_at=now,
            updated_at=now,
        )
        self._session.add(marketer)
        await self._session.flush()
        return MarketerRecord(marketer.id, company.id, user.id, user.email)
