"""Embeddingの元になる検索用テキストの生成（AGENT_DESIGN「過去施策の想起」「search_posts」）。"""

import re
import unicodedata

from core.canonical import sha256_hex
from domain.x_text import URL_PATTERN

_WHITESPACE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", text)).strip()


def build_campaign_search_text(
    target_profile: str, background: str, objective: str, plan: str
) -> str:
    """施策の検索用テキストを作る。表示用の title は含めない。"""
    return "\n".join(
        (
            f"ターゲット像: {_normalize(target_profile)}",
            f"実施背景: {_normalize(background)}",
            f"施策目的: {_normalize(objective)}",
            f"施策内容: {_normalize(plan)}",
        )
    )


def build_post_search_text(body: str) -> str:
    """投稿本文からURLを除去して正規化した検索用テキストを作る。"""
    return _normalize(URL_PATTERN.sub(" ", body))


def content_hash(search_text: str) -> str:
    """検索用テキストのSHA-256。内容が変わっていない場合の再生成を防ぐ。"""
    return sha256_hex(search_text)
