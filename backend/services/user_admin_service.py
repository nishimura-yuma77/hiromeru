"""自社ユーザー管理・招待（API_DESIGN 11.2、11.3、BE_STD 8.3）。

招待・再開・再送では、ユーザーと所属・送信操作・招待リンクをSES送信前のトランザクションで
確定し、送信結果はSESの応答後に別の短いトランザクションで記録する。送信失敗・結果不明でも
作成済みのユーザーとリンクを残す。SESはトランザクション内で呼ばない。
"""

import asyncio
import math
import random
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.exc import IntegrityError

from clients.email import (
    EmailMessage,
    EmailOutcomeUnknownError,
    EmailRejectedError,
    EmailThrottledError,
)
from core.errors import AppError
from core.logging import get_logger
from core.security import hash_invitation_token, hash_password, new_invitation_token
from domain.accounts import PasswordError, password_error
from domain.enums import EmailStatus, UserStatus
from repositories.users import (
    CompanyUserView,
    InvitationTarget,
    LockedUser,
    UserAdminRepository,
    UserType,
)
from services.context import AuthContext, ServiceContext

PAGE_SIZE = 20
# 初回送信と、明確なスロットリング応答に対する自動再試行2回。
MAX_SEND_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 0.5

_USER_TYPE_LABELS: dict[UserType, str] = {
    "admin": "管理ユーザー",
    "marketer": "マーケターユーザー",
}

_log = get_logger(__name__)


@dataclass(frozen=True)
class CompanyUserPage:
    """自社ユーザー一覧の1ページ。"""

    users: list[CompanyUserView]
    page: int
    page_size: int
    total_count: int
    total_pages: int


@dataclass(frozen=True)
class _PreparedSend:
    """SES送信前に確定した送信操作。トークンの平文はメール本文にだけ載せる。"""

    email_id: int
    message: EmailMessage


def _password_field_error(code: PasswordError) -> AppError:
    messages: dict[PasswordError, str] = {
        "REQUIRED": "パスワードを入力してください。",
        "TOO_LONG": "パスワードは128文字以内で入力してください。",
        "INVALID_FORMAT": (
            "パスワードは12文字以上で、空白を除く半角英数字・記号だけを使い、"
            "英大文字・英小文字・数字・記号をそれぞれ1文字以上含めてください。"
        ),
    }
    return AppError(
        "INVALID_ARGUMENT",
        field_errors=[{"field": "password", "code": code, "message": messages[code]}],
    )


class UserAdminService:
    """管理ユーザーによる自社ユーザーの一覧・招待・編集・停止・再開・再送と、招待の受諾。"""

    def __init__(self, ctx: ServiceContext) -> None:
        """サービスの依存を受け取る。"""
        self._ctx = ctx

    async def list(self, auth: AuthContext, page: int) -> CompanyUserPage:
        """自社ユーザーを20件ずつ返す。

        Raises:
            AppError: pageが最終ページを超える場合（INVALID_ARGUMENT）。0件の1ページ目は正常。
        """
        async with self._ctx.session_factory() as session:
            repository = UserAdminRepository(session)
            total = await repository.count_company_users(auth.company_id)
            total_pages = math.ceil(total / PAGE_SIZE)
            if page > max(total_pages, 1):
                raise AppError("INVALID_ARGUMENT", "page が範囲外です。")
            users = await repository.list_company_users(
                auth.company_id, offset=(page - 1) * PAGE_SIZE, limit=PAGE_SIZE
            )
        return CompanyUserPage(users, page, PAGE_SIZE, total, total_pages)

    async def invite(
        self, auth: AuthContext, *, user_type: UserType, name: str, email: str
    ) -> CompanyUserView:
        """招待中ユーザー・送信操作・招待リンクを保存してから招待メールを送る。

        Raises:
            AppError: メールアドレスが使用済み（USER_INVITATION_CONFLICT）、または送信失敗・
                結果不明（INVITATION_SEND_FAILED・INVITATION_SEND_OUTCOME_UNKNOWN）。
        """
        now = self._ctx.clock.now()
        try:
            async with self._ctx.session_factory() as session, session.begin():
                repository = UserAdminRepository(session)
                if await repository.email_exists(email):
                    raise AppError("USER_INVITATION_CONFLICT")
                user = await repository.create_invited_user(
                    company_id=auth.company_id,
                    name=name,
                    email=email,
                    user_type=user_type,
                    now=now,
                )
                prepared = await self._prepare_send(
                    repository, auth.company_id, user.id, name, email, user_type, now
                )
                user_id = user.id
        except IntegrityError:
            # 同時に同じメールアドレスで招待された場合。会社の違いは区別しない。
            raise AppError("USER_INVITATION_CONFLICT") from None
        _log.info("user_invited", company_id=auth.company_id, target_user_id=user_id)
        await self._deliver(prepared)
        return await self._view(auth, user_id)

    async def update(
        self,
        auth: AuthContext,
        user_id: int,
        *,
        name: str | None,
        user_type: UserType | None,
    ) -> CompanyUserView:
        """表示名とユーザー種別を部分更新する。実際に種別が変わるときだけ認証世代を更新する。

        Raises:
            AppError: 対象なし（ADMIN_USER_NOT_FOUND）、本人・責任者の種別変更
                （USER_ROLE_CHANGE_FORBIDDEN）、active以外の種別変更（USER_STATE_CONFLICT）。
        """
        now = self._ctx.clock.now()
        async with self._ctx.session_factory() as session, session.begin():
            repository = UserAdminRepository(session)
            target = await self._lock(repository, auth, user_id)
            changes_type = user_type is not None and user_type != target.user_type
            if changes_type:
                if target.user.id == auth.user_id or target.is_responsible:
                    raise AppError("USER_ROLE_CHANGE_FORBIDDEN")
                if target.user.status != UserStatus.ACTIVE:
                    raise AppError("USER_STATE_CONFLICT")
                if user_type == "admin":
                    await repository.add_admin(target.user.id, auth.company_id, now)
                else:
                    await repository.remove_admin(target.user.id)
                # 変更前の種別で発行したCookieを失効させる。
                target.user.auth_generation += 1
            if name is not None and name != target.user.name:
                target.user.name = name
            if changes_type or name is not None:
                target.user.updated_at = now
        if changes_type:
            _log.info(
                "user_type_changed",
                company_id=auth.company_id,
                target_user_id=user_id,
                user_type=user_type,
            )
        return await self._view(auth, user_id)

    async def suspend(self, auth: AuthContext, user_id: int) -> CompanyUserView:
        """招待中・利用中のユーザーを停止する。すでに停止中なら変更しない。

        Raises:
            AppError: 対象なし（ADMIN_USER_NOT_FOUND）、本人・責任者（USER_SUSPENSION_FORBIDDEN）。
        """
        now = self._ctx.clock.now()
        async with self._ctx.session_factory() as session, session.begin():
            repository = UserAdminRepository(session)
            target = await self._lock(repository, auth, user_id)
            if target.user.id == auth.user_id or target.is_responsible:
                raise AppError("USER_SUSPENSION_FORBIDDEN")
            if target.user.status != UserStatus.SUSPENDED:
                target.user.status = UserStatus.SUSPENDED
                target.user.password = None
                target.user.auth_generation += 1
                target.user.updated_at = now
                await repository.invalidate_open_invitations(target.user.id, now)
                _log.info("user_suspended", company_id=auth.company_id, target_user_id=user_id)
        return await self._view(auth, user_id)

    async def reactivate(self, auth: AuthContext, user_id: int) -> CompanyUserView:
        """停止中のユーザーを招待中へ戻し、新しい招待メールを送る。すでに招待中なら送らない。

        Raises:
            AppError: 対象なし（ADMIN_USER_NOT_FOUND）、利用中（USER_STATE_CONFLICT）、
                または送信失敗・結果不明。
        """
        now = self._ctx.clock.now()
        prepared: _PreparedSend | None = None
        async with self._ctx.session_factory() as session, session.begin():
            repository = UserAdminRepository(session)
            target = await self._lock(repository, auth, user_id)
            if target.user.status == UserStatus.ACTIVE:
                raise AppError("USER_STATE_CONFLICT")
            if target.user.status == UserStatus.SUSPENDED:
                target.user.status = UserStatus.INVITED
                target.user.auth_generation += 1
                target.user.updated_at = now
                await repository.invalidate_open_invitations(target.user.id, now)
                prepared = await self._prepare_send(
                    repository,
                    auth.company_id,
                    target.user.id,
                    target.user.name,
                    target.user.email,
                    target.user_type,
                    now,
                )
        if prepared is not None:
            _log.info("user_reactivated", company_id=auth.company_id, target_user_id=user_id)
            await self._deliver(prepared)
        return await self._view(auth, user_id)

    async def resend(self, auth: AuthContext, user_id: int) -> EmailStatus:
        """招待中のユーザーだけに、古いリンクを無効化して新しい招待メールを送る。

        Raises:
            AppError: 対象なし（ADMIN_USER_NOT_FOUND）、招待中以外（USER_STATE_CONFLICT）、
                または送信失敗・結果不明。
        """
        now = self._ctx.clock.now()
        async with self._ctx.session_factory() as session, session.begin():
            repository = UserAdminRepository(session)
            target = await self._lock(repository, auth, user_id)
            if target.user.status != UserStatus.INVITED:
                raise AppError("USER_STATE_CONFLICT")
            await repository.invalidate_open_invitations(target.user.id, now)
            prepared = await self._prepare_send(
                repository,
                auth.company_id,
                target.user.id,
                target.user.name,
                target.user.email,
                target.user_type,
                now,
            )
        _log.info("invitation_resent", company_id=auth.company_id, target_user_id=user_id)
        await self._deliver(prepared)
        return EmailStatus.ACCEPTED

    async def accept(self, token: str, password: str) -> UserType:
        """招待リンクからパスワードを設定し、ユーザーを利用中にする。

        リンクが無効ならパスワードの内容にかかわらず同じ `INVITATION_LINK_INVALID` とする。

        Raises:
            AppError: リンクが無効（INVITATION_LINK_INVALID）、パスワード条件違反
                （INVALID_ARGUMENT）。
        """
        token_hash = hash_invitation_token(token)
        async with self._ctx.session_factory() as session:
            found = await UserAdminRepository(session).find_invitation(token_hash)
        if found is None or not self._is_open(found, self._ctx.clock.now()):
            raise AppError("INVITATION_LINK_INVALID")
        code = password_error(password)
        if code is not None:
            raise _password_field_error(code)
        password_hash = await asyncio.to_thread(hash_password, password)
        async with self._ctx.session_factory() as session, session.begin():
            now = self._ctx.clock.now()
            # 二重使用を防ぐため、ロックしてから状態を確かめ直す。
            target = await UserAdminRepository(session).find_invitation(token_hash, lock=True)
            if target is None or not self._is_open(target, now):
                raise AppError("INVITATION_LINK_INVALID")
            target.invitation.used_at = now
            target.user.password = password_hash
            target.user.status = UserStatus.ACTIVE
            target.user.updated_at = now
            user_id, user_type = target.user.id, target.user_type
        _log.info("invitation_accepted", target_user_id=user_id)
        return user_type

    @staticmethod
    def _is_open(target: InvitationTarget, now: datetime) -> bool:
        invitation = target.invitation
        return (
            invitation.used_at is None
            and invitation.invalidated_at is None
            and now < invitation.expires_at
            and target.user.status == UserStatus.INVITED
        )

    @staticmethod
    async def _lock(repository: UserAdminRepository, auth: AuthContext, user_id: int) -> LockedUser:
        target = await repository.lock_company_user(auth.company_id, user_id)
        if target is None:
            # 存在しないユーザーと他社のユーザーを区別しない。
            raise AppError("ADMIN_USER_NOT_FOUND")
        return target

    async def _view(self, auth: AuthContext, user_id: int) -> CompanyUserView:
        async with self._ctx.session_factory() as session:
            view = await UserAdminRepository(session).get_company_user(auth.company_id, user_id)
        if view is None:
            raise AppError("ADMIN_USER_NOT_FOUND")
        return view

    async def _prepare_send(
        self,
        repository: UserAdminRepository,
        company_id: int,
        user_id: int,
        name: str,
        email: str,
        user_type: UserType,
        now: datetime,
    ) -> _PreparedSend:
        token = new_invitation_token()
        email_id = await repository.create_send(
            user_id=user_id, token_hash=hash_invitation_token(token), now=now
        )
        company_name = await repository.company_name(company_id)
        link = (
            f"{self._ctx.settings.resolved_invitation_base_url()}/invitations/accept?token={token}"
        )
        body = (
            f"{name} 様\n\n"
            f"{company_name} の{_USER_TYPE_LABELS[user_type]}として Hiromeru に招待されました。\n"
            "次のリンクからパスワードを設定して、利用を開始してください。\n\n"
            f"{link}\n\n"
            "このリンクの有効期限は発行から1時間です。期限が切れた場合は、"
            "管理者に再送を依頼してください。\n"
            "このメールに心当たりがない場合は、破棄してください。\n"
        )
        message = EmailMessage(to=email, subject=f"【Hiromeru】{company_name}への招待", body=body)
        return _PreparedSend(email_id, message)

    async def _deliver(self, prepared: _PreparedSend) -> None:
        """招待メールを送り、結果を記録する。受付成功以外は記録後にエラーを返す。

        明確なスロットリング応答だけ、同じリンクで最大2回、指数バックオフとジッターで
        自動再試行する。結果不明では自動再送しない。想定外の例外ではpendingのまま残し、
        一覧では結果不明として表示する。
        """
        attempts = 0
        status, message_id, error_code = EmailStatus.FAILED, None, "SES_THROTTLED"
        while attempts < MAX_SEND_ATTEMPTS:
            if attempts:
                delay = _BACKOFF_BASE_SECONDS * 2 ** (attempts - 1)
                await self._ctx.sleep(delay + random.uniform(0, delay))  # noqa: S311
            attempts += 1
            try:
                message_id = await self._ctx.email_client.send(prepared.message)
            except EmailThrottledError:
                continue
            except EmailRejectedError as error:
                status, error_code = EmailStatus.FAILED, f"SES_REJECTED_{error.status_code}"
            except EmailOutcomeUnknownError:
                status, error_code = EmailStatus.OUTCOME_UNKNOWN, "SES_OUTCOME_UNKNOWN"
            else:
                status, error_code = EmailStatus.ACCEPTED, None
            break
        async with self._ctx.session_factory() as session, session.begin():
            await UserAdminRepository(session).record_send_result(
                prepared.email_id,
                status=status,
                attempt_count=attempts,
                ses_message_id=message_id if status == EmailStatus.ACCEPTED else None,
                error_code=error_code,
                now=self._ctx.clock.now(),
            )
        _log.info(
            "invitation_email_sent",
            email_id=prepared.email_id,
            email_status=status,
            attempt_count=attempts,
            error_code=error_code,
        )
        if status == EmailStatus.FAILED:
            raise AppError("INVITATION_SEND_FAILED")
        if status == EmailStatus.OUTCOME_UNKNOWN:
            raise AppError("INVITATION_SEND_OUTCOME_UNKNOWN")
