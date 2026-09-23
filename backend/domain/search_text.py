"""Embeddingの元になる検索用テキストの生成（AGENT_DESIGN「過去施策の想起」「search_posts」）。"""

import re
import unicodedata

from core.canonical import sha256_hex
from domain.campaign_rules import CampaignContent
from domain.x_text import URL_PATTERN

_WHITESPACE = re.compile(r"\s+")


def normalize_search_text(text: str) -> str:
    """NFKCと空白の正規化を適用する。"""
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", text)).strip()


def build_campaign_search_text(content: CampaignContent) -> str:
    """施策の5項目から検索用テキストを作る。"""
    return "\n".join(
        (
            f"施策タイトル: {normalize_search_text(content.title)}",
            f"ターゲット像: {normalize_search_text(content.target_profile)}",
            f"実施背景: {normalize_search_text(content.background)}",
            f"施策目的: {normalize_search_text(content.objective)}",
            f"施策内容: {normalize_search_text(content.plan)}",
        )
    )


def build_post_search_text(body: str) -> str:
    """投稿本文からURLを除去して正規化した検索用テキストを作る。"""
    return normalize_search_text(URL_PATTERN.sub(" ", body))


def content_hash(search_text: str) -> str:
    """検索用テキストのSHA-256。内容が変わっていない場合の再生成を防ぐ。"""
    return sha256_hex(search_text)
