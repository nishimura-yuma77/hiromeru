"""署名付き一覧Snapshotカーソルの共通処理。"""

import uuid
from dataclasses import dataclass
from typing import Any

from core.canonical import canonical_json, sha256_hex
from core.errors import AppError
from core.security import sign_payload, verify_payload

_CURSOR_PURPOSE = "list-snapshot"


@dataclass(frozen=True)
class SnapshotCursor:
    """検証済みSnapshotカーソル。"""

    snapshot_id: uuid.UUID
    position: int
    filter_hash: str
    sort: str | None
    order: str | None


def snapshot_filter_hash(conditions: dict[str, Any]) -> str:
    """正規化済み一覧条件をSHA-256へ変換する。"""
    return sha256_hex(canonical_json(conditions))


def issue_snapshot_cursor(
    secret: str,
    resource: str,
    snapshot_id: uuid.UUID,
    position: int,
    filter_hash: str,
    sort: str | None = None,
    order: str | None = None,
) -> str:
    """Snapshot ID・次位置・条件Hashを改ざん不能なカーソルにする。"""
    if (sort is None) != (order is None):
        raise ValueError("sort と order は同時に指定してください")
    payload: dict[str, int | str] = {
        "r": resource,
        "s": str(snapshot_id),
        "p": position,
        "h": filter_hash,
    }
    if sort is not None and order is not None:
        payload.update({"sort": sort, "order": order})
    return sign_payload(secret, _CURSOR_PURPOSE, payload)


def read_snapshot_cursor(secret: str, resource: str, token: str) -> SnapshotCursor:
    """署名・一覧種別・各Fieldの型と範囲を検証する。"""
    payload = verify_payload(secret, _CURSOR_PURPOSE, token)
    try:
        if payload is None or payload.get("r") != resource:
            raise ValueError
        raw_snapshot_id = payload.get("s")
        position = payload.get("p")
        filter_hash = payload.get("h")
        sort = payload.get("sort")
        order = payload.get("order")
        if (
            not isinstance(raw_snapshot_id, str)
            or not isinstance(position, int)
            or isinstance(position, bool)
            or position <= 0
            or not isinstance(filter_hash, str)
            or len(filter_hash) != 64
            or ((sort is None) != (order is None))
            or (sort is not None and not isinstance(sort, str))
            or (order is not None and not isinstance(order, str))
        ):
            raise ValueError
        snapshot_id = uuid.UUID(raw_snapshot_id)
    except (ValueError, AttributeError):
        raise AppError("INVALID_ARGUMENT", "cursor が正しくありません。") from None
    return SnapshotCursor(snapshot_id, position, filter_hash, sort, order)
