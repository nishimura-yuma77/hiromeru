"""一覧APIの共通検証（API_DESIGN 6.1）。"""

from datetime import datetime

from core.errors import AppError
from domain.constants import MAX_SEARCH_QUERY_LENGTH
from domain.cursor import CursorError, CursorValue, decode_cursor
from domain.timefmt import parse_aware_datetime


def normalize_query(query: str | None) -> str | None:
    """検索語を検証する。前後の空白を除いて1文字以上、上限内であること。

    Raises:
        AppError: 空、または上限超過の場合（INVALID_ARGUMENT）。
    """
    if query is None:
        return None
    stripped = query.strip()
    if not stripped or len(stripped) > MAX_SEARCH_QUERY_LENGTH:
        raise AppError("INVALID_ARGUMENT", "query が正しくありません。")
    return stripped


def read_cursor(token: str, kind: str) -> dict[str, CursorValue]:
    """カーソルを検証して値を返す。

    Raises:
        AppError: 形式・種別が不正な場合（INVALID_ARGUMENT）。
    """
    try:
        return decode_cursor(token, kind)
    except CursorError:
        raise AppError("INVALID_ARGUMENT", "cursor が正しくありません。") from None


def require_int(values: dict[str, CursorValue], key: str) -> int:
    """カーソルの整数値を取り出す。"""
    value = values.get(key)
    if not isinstance(value, int):
        raise AppError("INVALID_ARGUMENT", "cursor が正しくありません。")
    return value


def require_datetime(values: dict[str, CursorValue], key: str) -> datetime:
    """カーソルの日時値を取り出す。"""
    value = values.get(key)
    try:
        if not isinstance(value, str):
            raise ValueError
        return parse_aware_datetime(value)
    except ValueError:
        raise AppError("INVALID_ARGUMENT", "cursor が正しくありません。") from None


def validate_range(start: datetime | None, end: datetime | None, name: str) -> None:
    """`*_from` が `*_to` 以上の場合は不正とする。

    Raises:
        AppError: 範囲が不正な場合（INVALID_ARGUMENT）。
    """
    if start is not None and end is not None and start >= end:
        raise AppError("INVALID_ARGUMENT", f"{name} の範囲が正しくありません。")
