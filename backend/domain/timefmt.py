"""日時の表記変換（API_DESIGN 2.5、6.1）。"""

from datetime import UTC, datetime


def format_utc(value: datetime) -> str:
    """UTCのISO 8601（末尾Z）へ変換する。マイクロ秒は、0でない場合だけ付ける。"""
    utc = value.astimezone(UTC)
    text = utc.strftime("%Y-%m-%dT%H:%M:%S")
    if utc.microsecond:
        text += f".{utc.microsecond:06d}"
    return f"{text}Z"


def parse_aware_datetime(value: str) -> datetime:
    """タイムゾーン付きのISO 8601文字列を解析する。

    Query文字列では `+` が空白に変換されることがあるため、空白は `+` として扱う。

    Raises:
        ValueError: 形式が不正、またはタイムゾーンがない場合。
    """
    parsed = datetime.fromisoformat(value.strip().replace(" ", "+"))
    if parsed.tzinfo is None:
        raise ValueError("タイムゾーンが必要です")
    return parsed.astimezone(UTC)
