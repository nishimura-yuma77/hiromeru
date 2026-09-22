"""リクエストBodyの解析と検証。"""

import json
from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Any

from pydantic import BaseModel, ValidationError

from core.errors import AppError, FieldError, FieldErrorCode

type BodyLoader = Callable[[], Awaitable[bytes]]

_FIELD_LABELS = {
    "email": "メールアドレス",
    "password": "パスワード",
    "title": "タイトル",
    "target_profile": "ターゲット像",
    "background": "実施背景",
    "objective": "施策目的",
    "plan": "施策内容",
    "expected_updated_at": "更新日時",
    "campaign_id": "施策ID",
    "body": "投稿本文",
    "landing_url": "遷移先URL",
    "message": "メッセージ",
}


def _field_name(location: tuple[int | str, ...]) -> str | None:
    parts = [str(part) for part in location]
    if len(parts) > 1 and parts[0] in ("body", "path", "query"):
        parts = parts[1:]
    return ".".join(parts) or None


def _field_error(
    field: str | None, code: FieldErrorCode, *, limit: int | None = None
) -> FieldError:
    label = _FIELD_LABELS.get(field or "", field or "入力内容")
    if code == "REQUIRED":
        message = f"{label}を入力してください。"
    elif code == "TOO_LONG" and limit is not None:
        message = f"{label}は{limit:,}文字以内で入力してください。"
    elif code == "TOO_LONG":
        message = f"{label}が文字数上限を超えています。"
    else:
        message = f"{label}の形式が正しくありません。"
    return {"field": field, "code": code, "message": message}


def validation_field_errors(details: Iterable[Mapping[str, Any]]) -> list[FieldError]:
    """Pydantic/FastAPIの検証結果を安定したField Errorへ変換する。"""
    field_errors: list[FieldError] = []
    for detail in details:
        field = _field_name(tuple(detail.get("loc", ())))
        error_type = str(detail.get("type", ""))
        context = detail.get("ctx") or {}
        if error_type in ("missing", "string_too_short"):
            field_errors.append(_field_error(field, "REQUIRED"))
        elif error_type == "string_too_long":
            field_errors.append(_field_error(field, "TOO_LONG", limit=context.get("max_length")))
        else:
            field_errors.append(_field_error(field, "INVALID_FORMAT"))
    return field_errors


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
        raise AppError(
            "INVALID_ARGUMENT",
            field_errors=validation_field_errors(
                error.errors(include_url=False, include_input=False)
            ),
        ) from None
