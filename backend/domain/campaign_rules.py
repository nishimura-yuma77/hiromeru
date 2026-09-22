"""施策の業務条件（API_DESIGN 4.1、4.2の`INVALID_CAMPAIGN`）。"""

from dataclasses import dataclass

from core.errors import FieldError


@dataclass(frozen=True)
class CampaignContent:
    """施策の編集可能な5項目。"""

    title: str
    target_profile: str
    background: str
    objective: str
    plan: str


def _has_forbidden_control_char(text: str, *, allow_newline: bool) -> bool:
    allowed = {"\n", "\r", "\t"} if allow_newline else set()
    return any(ord(char) < 32 and char not in allowed for char in text) or "\x7f" in text


def campaign_field_errors(content: CampaignContent) -> list[FieldError]:
    """業務条件に違反するFieldをすべて返す。

    設計書に具体的な条件がないため、次の2つを暫定の業務条件とする【要確認】。
    - タイトルは1行であること（改行を含まない）。
    - どの項目にも、改行・タブ以外の制御文字を含まないこと。
    """
    errors: list[FieldError] = []
    if "\n" in content.title or "\r" in content.title:
        errors.append(
            {
                "field": "title",
                "code": "INVALID_FORMAT",
                "message": "施策タイトルに改行を含めることはできません。",
            }
        )
    elif _has_forbidden_control_char(content.title, allow_newline=False):
        errors.append(
            {
                "field": "title",
                "code": "INVALID_FORMAT",
                "message": "施策タイトルに使用できない文字が含まれています。",
            }
        )
    fields = (
        ("target_profile", content.target_profile),
        ("background", content.background),
        ("objective", content.objective),
        ("plan", content.plan),
    )
    for field, value in fields:
        if _has_forbidden_control_char(value, allow_newline=True):
            errors.append(
                {
                    "field": field,
                    "code": "INVALID_FORMAT",
                    "message": "施策の内容に使用できない文字が含まれています。",
                }
            )
    return errors
