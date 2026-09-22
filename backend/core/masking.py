"""機密情報のマスク（REQUIREMENTS NFR-SEC-002）。

Agent履歴・ログ・エラーへ保存する前に、メールアドレス、電話番号、APIキー、
アクセストークン、カード番号を置換する。
"""

import re
from typing import Any, Final

MASK_EMAIL: Final = "[EMAIL]"
MASK_PHONE: Final = "[PHONE]"
MASK_SECRET: Final = "[SECRET]"
MASK_CARD: Final = "[CARD]"

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# sk-xxxx、ghp_xxxx、xoxb-xxxx など、サービス固有の秘密情報の代表的な形式。
_API_KEY = re.compile(
    r"\b(?:sk|pk|rk|ghp|gho|ghs|xox[abprs]|AKIA|AIza)[A-Za-z0-9_\-]{16,}\b|\bAKIA[0-9A-Z]{16}\b"
)
_BEARER = re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-~+/]{16,}=*")
_KEY_VALUE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|secret|password|passwd|token)\b(\s*[:=]\s*)"
    r"[^\s,;\"']+"
)
# 区切りの後ろの空白を巻き込まないよう、末尾は数字で終わらせる。
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,15}\d(?!\d)")
_PHONE = re.compile(r"(?<![\d-])(?:\+?\d{1,3}[ -]?)?\(?0?\d{1,4}\)?[ -]\d{1,4}[ -]\d{3,4}(?![\d-])")
_PHONE_COMPACT = re.compile(r"(?<!\d)0\d{9,10}(?!\d)")


def mask_text(text: str) -> str:
    """文字列内の機密情報をマスクする。"""
    # PostgreSQLのtext/jsonbへ保存できないNULを、監査履歴では安全な表記へ置き換える。
    masked = text.replace("\x00", "[NUL]")
    masked = _KEY_VALUE.sub(lambda m: f"{m.group(1)}{m.group(2)}{MASK_SECRET}", masked)
    masked = _BEARER.sub(lambda m: f"{m.group(1)} {MASK_SECRET}", masked)
    masked = _API_KEY.sub(MASK_SECRET, masked)
    masked = _EMAIL.sub(MASK_EMAIL, masked)
    masked = _CARD.sub(MASK_CARD, masked)
    masked = _PHONE.sub(MASK_PHONE, masked)
    return _PHONE_COMPACT.sub(MASK_PHONE, masked)


def mask_json(value: Any) -> Any:  # noqa: ANN401 - 任意のJSON値を再帰的に扱うため Any を許容する
    """JSON値（dict・list・str）内の文字列を再帰的にマスクする。"""
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, list):
        return [mask_json(item) for item in value]
    if isinstance(value, dict):
        return {
            mask_text(key) if isinstance(key, str) else key: mask_json(item)
            for key, item in value.items()
        }
    return value
