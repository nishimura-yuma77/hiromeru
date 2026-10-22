"""認証（両ログイン・ログイン中のユーザー取得）と初期設定。API_DESIGN 2.9、11.1。"""

import asyncio
from typing import Literal

from sqlalchemy.exc import IntegrityError

from core.errors import AppError
from core.security import hash_password, verify_password
from domain.accounts import is_valid_email, normalize_email, password_error
from domain.enums import UserStatus
from repositories.identity import AuthUser, IdentityRepository
from services.context import AuthContext, ServiceContext

type LoginPortal = Literal["marketer", "admin"]


class CompanySetupError(Exception):
    """初期設定スクリプトの入力が条件を満たさない。会社も責任者も登録しない。"""


class AuthService:
    """ログインと、認証Cookieからの認証済みContextの復元。"""

    def __init__(self, ctx: ServiceContext) -> None:
        """サービスの依存を受け取る。"""
        self._ctx = ctx

    async def login(self, email: str, password: str, *, portal: LoginPortal) -> AuthUser:
        """メールアドレスとパスワードを検証する。

        マーケター用の入口では管理ユーザーを、管理用の入口ではマーケターユーザーを拒否する。
        メールアドレス不明・パスワード不一致・active以外・入口違いはすべて同じ
        `INVALID_CREDENTIALS` とし、応答時間からも判別できないようにダミー照合を行う。

        Raises:
            AppError: 認証に失敗した場合（INVALID_CREDENTIALS）。
        """
        async with self._ctx.session_factory() as session:
            found = await IdentityRepository(session).find_login_target(normalize_email(email))
        record, password_hash = found if found is not None else (None, None)
        # argon2 はCPU負荷が高いため、イベントループを止めないよう別スレッドで実行する。
        matched = await asyncio.to_thread(verify_password, password, password_hash)
        if record is None or not matched or record.status != UserStatus.ACTIVE:
            raise AppError("INVALID_CREDENTIALS")
        if record.is_admin != (portal == "admin"):
            raise AppError("INVALID_CREDENTIALS")
        return record

    async def authenticate(self, user_id: int, auth_generation: int) -> AuthContext | None:
        """認証Cookieから認証済みContextを復元する。

        active でない、または認証世代が一致しない場合は None（変更前のCookieを失効させる）。
        """
        async with self._ctx.session_factory() as session:
            record = await IdentityRepository(session).get_auth_user(user_id)
        if (
            record is None
            or record.status != UserStatus.ACTIVE
            or record.auth_generation != auth_generation
        ):
            return None
        return AuthContext(record.user_id, record.company_id, record.email, record.is_admin)

    async def create_company(
        self, *, company_name: str, name: str, email: str, password: str
    ) -> AuthUser:
        """会社と責任者を同一トランザクションで登録する（初期設定スクリプト用）。

        Raises:
            CompanySetupError: 入力が条件を満たさない、またはメールアドレスが使用済みの場合。
        """
        company_name, name, normalized = company_name.strip(), name.strip(), normalize_email(email)
        if not company_name or len(company_name) > 255:
            raise CompanySetupError("会社名は1～255文字で指定してください")
        if not name or len(name) > 255:
            raise CompanySetupError("表示名は1～255文字で指定してください")
        if not is_valid_email(normalized):
            raise CompanySetupError("メールアドレスの形式が正しくありません")
        if password_error(password) is not None:
            raise CompanySetupError(
                "パスワードは12～128文字で、空白を除く半角英数字・記号だけを使い、"
                "英大文字・英小文字・数字・記号をそれぞれ1文字以上含めてください"
            )
        password_hash = await asyncio.to_thread(hash_password, password)
        try:
            async with self._ctx.session_factory() as session, session.begin():
                repository = IdentityRepository(session)
                if await repository.email_exists(normalized):
                    raise CompanySetupError("このメールアドレスはすでに使われています")
                return await repository.create_company_with_responsible(
                    company_name=company_name,
                    name=name,
                    email=normalized,
                    password_hash=password_hash,
                    now=self._ctx.clock.now(),
                )
        except IntegrityError as error:
            # 同時に同じメールアドレスで登録された場合。会社を含めてロールバック済み。
            raise CompanySetupError("このメールアドレスはすでに使われています") from error
