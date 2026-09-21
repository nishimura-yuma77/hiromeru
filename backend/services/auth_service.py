"""認証（ログイン・ログイン中のマーケター取得）。API_DESIGN 2.9。"""

import asyncio

from core.errors import AppError
from core.security import hash_password, verify_password
from repositories.identity import IdentityRepository, MarketerRecord
from services.context import AuthContext, ServiceContext


class AuthService:
    """ログインと、認証Cookieからの認証済みContextの復元。"""

    def __init__(self, ctx: ServiceContext) -> None:
        """サービスの依存を受け取る。"""
        self._ctx = ctx

    async def login(self, email: str, password: str) -> MarketerRecord:
        """メールアドレスとパスワードを検証する。

        メールアドレスがない・パスワードが違う・マーケタープロファイルがない、のどれも
        同じ `INVALID_CREDENTIALS` とし、応答時間からも判別できないようにダミー照合を行う。

        Raises:
            AppError: 認証に失敗した場合（INVALID_CREDENTIALS）。
        """
        async with self._ctx.session_factory() as session:
            found = await IdentityRepository(session).find_login_target(email.lower())
        record, password_hash = found if found is not None else (None, None)
        # argon2 はCPU負荷が高いため、イベントループを止めないよう別スレッドで実行する。
        matched = await asyncio.to_thread(verify_password, password, password_hash)
        if record is None or not matched:
            raise AppError("INVALID_CREDENTIALS")
        return record

    async def authenticate(self, marketer_id: int) -> AuthContext | None:
        """認証Cookieの `marketer_id` から認証済みContextを復元する。行がなければ None。"""
        async with self._ctx.session_factory() as session:
            record = await IdentityRepository(session).get_marketer(marketer_id)
        if record is None:
            return None
        return AuthContext(record.marketer_id, record.company_id, record.user_id, record.email)

    async def create_marketer(
        self, *, company_name: str, marketer_name: str, email: str, password: str
    ) -> MarketerRecord:
        """会社・ユーザー・マーケターを作成する（初期データ投入スクリプト用）。"""
        password_hash = await asyncio.to_thread(hash_password, password)
        async with self._ctx.session_factory() as session, session.begin():
            return await IdentityRepository(session).create_account(
                company_name=company_name,
                marketer_name=marketer_name,
                email=email.strip().lower(),
                password_hash=password_hash,
                now=self._ctx.clock.now(),
            )
