"""Request Bodyの正規化とハッシュ（API_DESIGN 2.3）。"""

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:  # noqa: ANN401 - 任意のJSON値を扱うため Any を許容する
    """キー順や空白などの表現上の差を除いたJSON文字列を返す。"""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(text: str) -> str:
    """文字列のSHA-256（16進64文字）を返す。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def request_hash(body: Any) -> str:  # noqa: ANN401 - 任意のJSON値を扱うため Any を許容する
    """Request BodyのSHA-256を返す。"""
    return sha256_hex(canonical_json(body))
