"""時刻取得。テストで固定できるよう、直接 `datetime.now()` を呼ばず注入する（BE_STD 4章）。"""

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    """現在時刻（UTC、タイムゾーン付き）を返す。"""

    def now(self) -> datetime:
        """現在のUTC時刻を返す。"""
        ...


class SystemClock:
    """システム時計。"""

    def now(self) -> datetime:
        """現在のUTC時刻を返す。"""
        return datetime.now(UTC)
