"""Xの文字数規則（API_DESIGN 3.1）。

Xの現行規則（twitter-text）に従い、URLは23、ラテン文字など一部の範囲は1、
CJKなどそれ以外は2として数える。上限は280。
"""

import re
import unicodedata

from domain.constants import X_MAX_WEIGHTED_LENGTH, X_URL_WEIGHT

URL_PATTERN = re.compile(r"https?://[^\s]+", re.IGNORECASE)

# 重み1として数えるコードポイントの範囲（twitter-text の config v3）。
_WEIGHT_ONE_RANGES = (
    (0, 4351),
    (8192, 8205),
    (8208, 8223),
    (8242, 8247),
)


def _char_weight(char: str) -> int:
    code = ord(char)
    return 1 if any(low <= code <= high for low, high in _WEIGHT_ONE_RANGES) else 2


def weighted_length(text: str) -> int:
    """Xの規則で数えた文字数を返す。"""
    normalized = unicodedata.normalize("NFC", text)
    total = 0
    position = 0
    for match in URL_PATTERN.finditer(normalized):
        total += sum(_char_weight(char) for char in normalized[position : match.start()])
        total += X_URL_WEIGHT
        position = match.end()
    total += sum(_char_weight(char) for char in normalized[position:])
    return total


def contains_url(text: str) -> bool:
    """文字列にURLが含まれるか。"""
    return URL_PATTERN.search(text) is not None


def is_within_x_limit(text: str) -> bool:
    """Xの文字数上限（280）以内か。"""
    return weighted_length(text) <= X_MAX_WEIGHTED_LENGTH
