"""認証Cookieと `csrf_token` Cookieの組み立て（API_DESIGN 2.8）。"""

from datetime import datetime

from core.config import Settings
from domain.constants import CSRF_COOKIE_NAME, SESSION_ABSOLUTE_SECONDS, SESSION_COOKIE_NAME

_EPOCH = "Thu, 01 Jan 1970 00:00:00 GMT"


def _cookie(
    name: str,
    value: str,
    *,
    max_age: int,
    secure: bool,
    http_only: bool,
    expires: str | None = None,
) -> str:
    parts = [f"{name}={value}", f"Max-Age={max_age}", "Path=/", "SameSite=lax"]
    if expires is not None:
        parts.append(f"Expires={expires}")
    if http_only:
        parts.append("HttpOnly")
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def session_cookie(settings: Settings, token: str, idle_expires_at: datetime, now: datetime) -> str:
    """認証Cookie（HttpOnly）。有効期間はアイドル期限までとする。"""
    max_age = max(0, int((idle_expires_at - now).total_seconds()))
    return _cookie(
        SESSION_COOKIE_NAME, token, max_age=max_age, secure=settings.cookie_secure, http_only=True
    )


def csrf_cookie(settings: Settings, token: str) -> str:
    """`csrf_token` Cookie。JavaScriptが読めるよう HttpOnly にしない。"""
    return _cookie(
        CSRF_COOKIE_NAME,
        token,
        max_age=SESSION_ABSOLUTE_SECONDS,
        secure=settings.cookie_secure,
        http_only=False,
    )


def deletion_cookies(settings: Settings) -> list[str]:
    """認証Cookieと `csrf_token` Cookieを削除する `Set-Cookie` の値。"""
    return [
        _cookie(
            SESSION_COOKIE_NAME,
            "",
            max_age=0,
            secure=settings.cookie_secure,
            http_only=True,
            expires=_EPOCH,
        ),
        _cookie(
            CSRF_COOKIE_NAME,
            "",
            max_age=0,
            secure=settings.cookie_secure,
            http_only=False,
            expires=_EPOCH,
        ),
    ]
