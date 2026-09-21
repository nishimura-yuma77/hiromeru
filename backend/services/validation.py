"""リクエストBodyの解析と検証。"""

import json
from typing import Any

from pydantic import BaseModel, ValidationError

from core.errors import AppError
from domain.requests import first_error_field


def parse_json_object(raw: bytes) -> dict[str, Any]:
    """Request Bodyを安全にJSONオブジェクトとして解析する。

    Raises:
        AppError: JSONでない、またはオブジェクトでない場合（INVALID_ARGUMENT）。
    """
    try:
        parsed = json.loads(raw)
    except (ValueError, RecursionError):
        raise AppError("INVALID_ARGUMENT", "リクエストがJSONとして解析できません。") from None
    if not isinstance(parsed, dict):
        raise AppError("INVALID_ARGUMENT", "リクエストはJSONオブジェクトで指定してください。")
    return parsed


def validate_model[ModelT: BaseModel](model: type[ModelT], data: dict[str, Any]) -> ModelT:
    """スキーマで検証する。

    Raises:
        AppError: 型・必須項目・長さが不正な場合（INVALID_ARGUMENT）。入力値は含めない。
    """
    try:
        return model.model_validate(data)
    except ValidationError as error:
        field = first_error_field(error)
        raise AppError(
            "INVALID_ARGUMENT", f"リクエストの内容が正しくありません（{field}）。"
        ) from None
