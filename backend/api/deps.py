"""認証・CSRFの依存関係（API_DESIGN 2.8）。認証 → CSRF の順に検証する。"""

from typing import Annotated

from fastapi import Depends, Request

from api.container import get_service_context
from api.cookies import session_cookie
from core.config import normalize_origin
from core.errors import AppError
from core.security import csrf_token_matches, issue_session_token, read_session_token
from domain.constants import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, SESSION_COOKIE_NAME
from services.auth_service import AuthService
from services.context import AuthContext, ServiceContext

# 認証済みRequestのResponseで、アイドル期限を延長するCookieを発行するための scope キー。
REISSUE_COOKIE_KEY = "hiromeru.reissue_cookie"

Context = Annotated[ServiceContext, Depends(get_service_context)]


def verify_origin(request: Request, ctx: Context) -> None:
    """`Origin`（なければ `Referer`）が許可リストと一致することを検証する。

    Raises:
        AppError: 不一致、またはどちらのHeaderもない場合（CSRF_VALIDATION_FAILED）。
    """
    origin = request.headers.get("origin") or request.headers.get("referer")
    if not origin or origin == "null":
        raise AppError("CSRF_VALIDATION_FAILED")
    if normalize_origin(origin) not in ctx.settings.resolved_allowed_origins():
        raise AppError("CSRF_VALIDATION_FAILED")


async def authenticated(request: Request, ctx: Context) -> AuthContext:
    """認証Cookieを検証し、認証済みContextを返す。Cookieを発行し直してアイドル期限を延長する。

    Raises:
        AppError: Cookieがない・署名不正・期限切れ・マーケターの行がない場合（UNAUTHENTICATED）。
    """
    token = request.cookies.get(SESSION_COOKIE_NAME)
    now = ctx.clock.now()
    session = read_session_token(ctx.settings.session_secret, token, now) if token else None
    if session is None:
        raise AppError("UNAUTHENTICATED")
    auth = await AuthService(ctx).authenticate(session.marketer_id)
    if auth is None:
        raise AppError("UNAUTHENTICATED")
    new_token, idle_expires_at = issue_session_token(
        ctx.settings.session_secret, auth.marketer_id, session.issued_at, now
    )
    request.scope[REISSUE_COOKIE_KEY] = session_cookie(
        ctx.settings, new_token, idle_expires_at, now
    )
    return auth


Authenticated = Annotated[AuthContext, Depends(authenticated)]


def csrf_protected(request: Request, ctx: Context, auth: Authenticated) -> AuthContext:
    """状態変更APIの保護。Origin検証と、署名付きダブルサブミットトークンの検証を行う。"""
    verify_origin(request, ctx)
    cookie_value = request.cookies.get(CSRF_COOKIE_NAME, "")
    header_value = request.headers.get(CSRF_HEADER_NAME, "")
    if not csrf_token_matches(
        ctx.settings.session_secret, auth.marketer_id, cookie_value, header_value
    ):
        raise AppError("CSRF_VALIDATION_FAILED")
    return auth


CsrfProtected = Annotated[AuthContext, Depends(csrf_protected)]
OriginChecked = Depends(verify_origin)
