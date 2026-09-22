"""Query文字列の解析。"""

from datetime import datetime

from core.errors import AppError
from domain.timefmt import parse_aware_datetime


def parse_query_datetime(value: str | None, name: str) -> datetime | None:
    """タイムゾーン付きのISO 8601をUTCの日時へ変換する。

    Raises:
        AppError: 形式が不正、またはタイムゾーンがない場合（INVALID_ARGUMENT）。
    """
    if value is None:
        return None
    try:
        return parse_aware_datetime(value)
    except ValueError:
        raise AppError("INVALID_ARGUMENT", f"{name} が正しくありません。") from None
