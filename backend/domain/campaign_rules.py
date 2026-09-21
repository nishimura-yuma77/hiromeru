"""施策の業務条件（API_DESIGN 4.1、4.2の`INVALID_CAMPAIGN`）。"""

from dataclasses import dataclass


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


def find_campaign_violation(content: CampaignContent) -> str | None:
    """業務条件に違反する場合、利用者向けの理由を返す。違反がなければ None。

    設計書に具体的な条件がないため、次の2つを暫定の業務条件とする【要確認】。
    - タイトルは1行であること（改行を含まない）。
    - どの項目にも、改行・タブ以外の制御文字を含まないこと。
    """
    if "\n" in content.title or "\r" in content.title:
        return "施策タイトルに改行を含めることはできません。"
    if _has_forbidden_control_char(content.title, allow_newline=False):
        return "施策タイトルに使用できない文字が含まれています。"
    for value in (content.target_profile, content.background, content.objective, content.plan):
        if _has_forbidden_control_char(value, allow_newline=True):
            return "施策の内容に使用できない文字が含まれています。"
    return None
