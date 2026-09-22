"""パスワードのハッシュと、認証Cookie・CSRFトークンの署名（API_DESIGN 2.8、BE_STD 15章）。"""

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from domain.constants import SESSION_ABSOLUTE_SECONDS, SESSION_IDLE_SECONDS

_hasher = PasswordHasher()
# ユーザーが存在しない場合も同等の照合処理を行い、応答時間から登録の有無を判別させない。
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing-equalization")


def hash_password(password: str) -> str:
    """パスワードをargon2でハッシュ化する。CPU負荷が高いため、非同期からは to_thread で呼ぶ。"""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """パスワードを照合する。`password_hash` が None のときはダミーのハッシュと照合して False。"""
    target = password_hash or _DUMMY_HASH
    try:
        matched = _hasher.verify(target, password)
    except (VerificationError, InvalidHashError):
        return False
    return matched and password_hash is not None


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _signature(secret: str, purpose: str, body: str) -> str:
    digest = hmac.new(secret.encode(), f"{purpose}.{body}".encode(), hashlib.sha256).digest()
    return _b64encode(digest)


def sign_payload(secret: str, purpose: str, payload: dict[str, int | str]) -> str:
    """ペイロードに署名し、`<本体>.<署名>` の文字列を返す。用途（purpose）を署名へ含める。"""
    body = _b64encode(json.dumps(payload, separators=(",", ":")).encode())
    return f"{body}.{_signature(secret, purpose, body)}"


def verify_payload(secret: str, purpose: str, token: str) -> dict[str, int | str] | None:
    """署名を検証してペイロードを返す。不正な場合は None を返す。"""
    body, dot, signature = token.partition(".")
    if not dot or not hmac.compare_digest(signature, _signature(secret, purpose, body)):
        return None
    try:
        payload = json.loads(_b64decode(body))
    except (ValueError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


_SESSION_PURPOSE = "session"
_CSRF_PURPOSE = "csrf"


@dataclass(frozen=True)
class SessionToken:
    """認証Cookieの内容。"""

    marketer_id: int
    issued_at: datetime
    idle_expires_at: datetime

    @property
    def absolute_expires_at(self) -> datetime:
        """ログイン日時から7日の絶対上限。延長しない。"""
        return self.issued_at + timedelta(seconds=SESSION_ABSOLUTE_SECONDS)


def issue_session_token(
    secret: str, marketer_id: int, issued_at: datetime, now: datetime
) -> tuple[str, datetime]:
    """認証Cookieの値と、そのアイドル期限を返す。

    アイドル期限は今から8時間先とし、絶対上限（ログインから7日）を超えない。
    """
    absolute = issued_at + timedelta(seconds=SESSION_ABSOLUTE_SECONDS)
    idle = min(now + timedelta(seconds=SESSION_IDLE_SECONDS), absolute)
    token = sign_payload(
        secret,
        _SESSION_PURPOSE,
        {"m": marketer_id, "iat": int(issued_at.timestamp()), "exp": int(idle.timestamp())},
    )
    return token, idle


def read_session_token(secret: str, token: str, now: datetime) -> SessionToken | None:
    """認証Cookieを検証する。署名不正、またはいずれかの期限を超えていれば None。"""
    payload = verify_payload(secret, _SESSION_PURPOSE, token)
    if payload is None:
        return None
    marketer_id, issued, expires = payload.get("m"), payload.get("iat"), payload.get("exp")
    if not (isinstance(marketer_id, int) and isinstance(issued, int) and isinstance(expires, int)):
        return None
    session = SessionToken(
        marketer_id=marketer_id,
        issued_at=datetime.fromtimestamp(issued, tz=now.tzinfo),
        idle_expires_at=datetime.fromtimestamp(expires, tz=now.tzinfo),
    )
    if now >= session.idle_expires_at or now >= session.absolute_expires_at:
        return None
    return session


def issue_csrf_token(secret: str, marketer_id: int) -> str:
    """マーケターに束縛した署名付きCSRFトークンを発行する。"""
    return sign_payload(secret, _CSRF_PURPOSE, {"m": marketer_id, "n": secrets.token_urlsafe(16)})


def csrf_token_matches(secret: str, marketer_id: int, cookie_value: str, header_value: str) -> bool:
    """CookieとHeaderの値が一致し、署名が有効で、マーケターに束縛されているか検証する。"""
    if not cookie_value or not hmac.compare_digest(cookie_value, header_value):
        return False
    payload = verify_payload(secret, _CSRF_PURPOSE, cookie_value)
    return payload is not None and payload.get("m") == marketer_id
