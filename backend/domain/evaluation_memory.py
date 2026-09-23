"""Metricsから生成する決定論的な評価記憶。"""

from domain.search_text import build_post_search_text, normalize_search_text


def build_evaluation_memory_content(
    campaign_title: str,
    post_body: str,
    x_pv_count: int,
    landing_user_count: int,
) -> str:
    """外部LLMを使わず、固定5行Templateを生成する。"""
    rate = "算出不可（初週PVが0）" if x_pv_count == 0 else f"{landing_user_count}/{x_pv_count}"
    return "\n".join(
        (
            f"施策タイトル: {normalize_search_text(campaign_title)}",
            f"投稿本文: {build_post_search_text(post_body)}",
            f"初週PV: {x_pv_count}",
            f"流入ユーザー: {landing_user_count}",
            f"流入率: {rate}",
        )
    )
