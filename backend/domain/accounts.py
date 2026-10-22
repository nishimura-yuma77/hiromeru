"""ユーザーのメールアドレスとパスワードの規則（REQUIREMENTS 2.6、API_DESIGN 11章）。

初期設定スクリプト・招待・ログインで同じ規則を使う。
"""

import re
from typing import Literal

MAX_EMAIL_LENGTH = 255
MAX_USER_NAME_LENGTH = 255
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128

# 空白を除く半角英数字・記号（ASCII 0x21～0x7E）。
_PASSWORD_CHARS = re.compile(r"[\x21-\x7e]+")
# 形式の検証は最小限とし、到達性はメール送信で確かめる。
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

type PasswordError = Literal["REQUIRED", "TOO_LONG", "INVALID_FORMAT"]


def normalize_email(email: str) -> str:
    """前後の空白を除き、小文字にする。全社一意の判定と保存にこの値を使う。"""
    return email.strip().lower()


def is_valid_email(email: str) -> bool:
    """正規化済みのメールアドレスの形式と長さを検証する。"""
    return len(email) <= MAX_EMAIL_LENGTH and _EMAIL.fullmatch(email) is not None


def password_error(password: str) -> PasswordError | None:
    """新しく設定するパスワードの違反を返す。条件を満たせば None。

    12～128文字で、空白を除く半角英数字・記号だけを使い、英大文字・英小文字・数字・
    記号をそれぞれ1文字以上含める。
    """
    if not password:
        return "REQUIRED"
    if len(password) > MAX_PASSWORD_LENGTH:
        return "TOO_LONG"
    if len(password) < MIN_PASSWORD_LENGTH or _PASSWORD_CHARS.fullmatch(password) is None:
        return "INVALID_FORMAT"
    classes = (
        any(c.isupper() for c in password),
        any(c.islower() for c in password),
        any(c.isdigit() for c in password),
        any(not c.isalnum() for c in password),
    )
    return None if all(classes) else "INVALID_FORMAT"
