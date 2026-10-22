"""時刻取得。テストで固定できるよう、直接 `datetime.now()` を呼ばず注入する（BE_STD 4章）。"""

from datetime import UTC, datetime, timedelta
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


class AdjustableClock:
    """E2E専用の時計。基準の時計に、テストから進めた時間を加える。"""

    def __init__(self, base: Clock) -> None:
        """基準の時計を受け取る。"""
        self._base = base
        self._offset = timedelta(0)

    def now(self) -> datetime:
        """進めた時間を加えた現在時刻を返す。"""
        return self._base.now() + self._offset

    def advance(self, seconds: float) -> None:
        """時刻を進める。招待リンクや認証Cookieの期限切れを再現する。"""
        self._offset += timedelta(seconds=seconds)

    def reset(self) -> None:
        """進めた時間を戻す。"""
        self._offset = timedelta(0)
