"""一覧APIの不透明なカーソル（API_DESIGN 5.5、6.1）。クライアントは解釈しない。"""

import base64
import json


class CursorError(ValueError):
    """カーソルの形式または種別が不正。"""


type CursorValue = str | int | None


def encode_cursor(kind: str, values: dict[str, CursorValue]) -> str:
    """種別と値からカーソル文字列を作る。"""
    raw = json.dumps({"k": kind, "v": values}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode_cursor(token: str, kind: str) -> dict[str, CursorValue]:
    """カーソル文字列を検証して値を返す。

    Raises:
        CursorError: 形式が不正、または別の一覧の種別のカーソルの場合。
    """
    try:
        payload = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
    except (ValueError, UnicodeDecodeError) as error:
        raise CursorError("カーソルの形式が不正です") from error
    if not isinstance(payload, dict) or payload.get("k") != kind:
        raise CursorError("カーソルの種別が一致しません")
    values = payload.get("v")
    if not isinstance(values, dict):
        raise CursorError("カーソルの値が不正です")
    return values
