"""Create or remove the deterministic local demo tenant."""

import argparse
import hashlib
import json
import re
import unicodedata
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from core.config import get_settings

_BIND: ContextVar[Connection] = ContextVar("demo_dataset_bind")

_DEMO_EMAIL = "demo@hiromeru.local"
_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$VRB1pVPuipMnilcBxIl+Kg$"
    "DOoYSY5eqDHZ386krXEfVvkAF6CTZAjiSy9FqpXxeXU"
)
_COMPANY_ID = 9_003_000_001
_USER_ID = 9_003_000_001
_MARKETER_ID = 9_003_000_001
_CAMPAIGN_IDS = (9_003_001_001, 9_003_001_002, 9_003_001_003)
_SESSION_IDS = (9_003_002_001, 9_003_002_002, 9_003_002_003)
_TURN_IDS = tuple(range(9_003_003_001, 9_003_003_008))
_ITEM_IDS = tuple(range(9_003_004_001, 9_003_004_015))
_REQUEST_IDS = tuple(range(9_003_005_001, 9_003_005_005))
_POST_IDS = tuple(range(9_003_006_001, 9_003_006_005))
_TRACKING_IDS = tuple(range(9_003_007_001, 9_003_007_005))
_MEMORY_IDS = tuple(range(9_003_008_001, 9_003_008_005))
_LLM_IDS = tuple(range(9_003_009_001, 9_003_009_004))
_KEYS = tuple(f"90030000-0000-4000-8000-{number:012d}" for number in range(1, 5))

_CAMPAIGNS = (
    {
        "id": _CAMPAIGN_IDS[0],
        "title": "開発者の一日を伝える採用施策",
        "target_profile": "転職を検討中で、働き方やチームの雰囲気を重視するWebエンジニア",
        "background": "求人票だけでは、入社後の働き方や開発チームの日常が伝わりにくい。",
        "objective": "開発現場への理解を深め、採用ページへの質の高い流入を増やす。",
        "plan": "開発者の一日を時系列で紹介し、仕事の進め方とチーム文化を具体的に伝える。",
        "created_at": datetime(2026, 7, 6, 9, 0, tzinfo=UTC),
    },
    {
        "id": _CAMPAIGN_IDS[1],
        "title": "フルリモート開発文化の紹介",
        "target_profile": "居住地に縛られず、裁量を持って働きたい経験者エンジニア",
        "background": "リモート勤務制度は知られているが、実際の連携方法や働きやすさが伝わっていない。",
        "objective": "リモート環境への不安を減らし、カジュアル面談への関心を高める。",
        "plan": "非同期コミュニケーション、定例、開発環境を社員の実例とともに紹介する。",
        "created_at": datetime(2026, 8, 3, 9, 0, tzinfo=UTC),
    },
    {
        "id": _CAMPAIGN_IDS[2],
        "title": "若手エンジニア向け技術発信",
        "target_profile": "実務経験1〜3年で、学習環境と成長機会を重視するエンジニア",
        "background": "社内の技術知見や育成文化が候補者へ十分に届いていない。",
        "objective": "技術への取り組みを継続的に届け、採用候補者との接点を増やす。",
        "plan": "レビュー文化、勉強会、技術選定の背景を短い連載として発信する。",
        "created_at": datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
    },
)

_POSTS = (
    {
        "id": _POST_IDS[0],
        "campaign_id": _CAMPAIGN_IDS[0],
        "body": "朝会からレビューまで、開発者の一日を紹介します。制度名だけでは見えない、チームで働く時間をまとめました。",
        "landing_url": "https://hiromeru.local/demo/engineer-day",
        "x_post_id": "demo-x-post-9003006001",
        "published_at": datetime(2026, 7, 15, 2, 30, tzinfo=UTC),
        "x_pv_count": 1840,
        "landing_user_count": 132,
    },
    {
        "id": _POST_IDS[1],
        "campaign_id": _CAMPAIGN_IDS[0],
        "body": "仕様相談は早めに、集中時間はしっかり確保。開発チームが大切にしている一日のリズムを紹介します。",
        "landing_url": "https://hiromeru.local/demo/development-culture",
        "x_post_id": "demo-x-post-9003006002",
        "published_at": datetime(2026, 7, 29, 6, 0, tzinfo=UTC),
        "x_pv_count": 2310,
        "landing_user_count": 196,
    },
    {
        "id": _POST_IDS[2],
        "campaign_id": _CAMPAIGN_IDS[1],
        "body": "フルリモートでも相談しやすいチームへ。非同期の共有と週次の対話をどう使い分けているか紹介します。",
        "landing_url": "https://hiromeru.local/demo/remote-work",
        "x_post_id": "demo-x-post-9003006003",
        "published_at": datetime(2026, 8, 20, 3, 15, tzinfo=UTC),
        "x_pv_count": 3260,
        "landing_user_count": 281,
    },
    {
        "id": _POST_IDS[3],
        "campaign_id": _CAMPAIGN_IDS[2],
        "body": "コードレビューを、指摘ではなく学びの場に。若手メンバーが成長しやすいレビュー文化を紹介します。",
        "landing_url": "https://hiromeru.local/demo/code-review",
        "x_post_id": "demo-x-post-9003006004",
        "published_at": datetime(2026, 9, 20, 1, 45, tzinfo=UTC),
        "x_pv_count": None,
        "landing_user_count": None,
    },
)

_MEMORIES = (
    "制度名だけより、開発者の一日の流れを具体的に示した投稿の反応が良かった。",
    "業務内容に加えて、相談のしやすさを伝えると採用ページへの流入が増えた。",
    "フルリモート訴求では、制度より実際のコミュニケーション方法が関心を集めた。",
    "若手向けの発信では、技術スタックの列挙よりレビューの具体例が伝わりやすい。",
)

_MEMORY_CAMPAIGNS = (
    (_MEMORY_IDS[0], _CAMPAIGN_IDS[0]),
    (_MEMORY_IDS[1], _CAMPAIGN_IDS[0]),
    (_MEMORY_IDS[2], _CAMPAIGN_IDS[1]),
    (_MEMORY_IDS[3], _CAMPAIGN_IDS[2]),
)
_MEMORY_POSTS = (
    (_MEMORY_IDS[0], _POST_IDS[0]),
    (_MEMORY_IDS[0], _POST_IDS[1]),
    (_MEMORY_IDS[1], _POST_IDS[1]),
    (_MEMORY_IDS[2], _POST_IDS[2]),
    (_MEMORY_IDS[3], _POST_IDS[3]),
)

_COLUMN_CASTS = {
    ("agent_memories", "embedding"): "vector(1536)",
    ("agent_sessions", "agent"): "agent_type",
    ("agent_turns", "status"): "agent_turn_status",
    ("campaign_embeddings", "embedding"): "vector(1536)",
    ("api_idempotency_requests", "operation"): "api_operation",
    ("api_idempotency_requests", "idempotency_key"): "uuid",
    ("api_idempotency_requests", "status"): "api_idempotency_status",
    ("api_idempotency_requests", "execution_token"): "uuid",
    ("api_idempotency_requests", "external_result"): "jsonb",
    ("api_idempotency_requests", "response_body"): "jsonb",
    ("agent_items", "item_type"): "agent_item_type",
    ("agent_items", "context_class"): "agent_context_class",
    ("agent_items", "content_source"): "agent_content_source",
    ("agent_items", "context_status"): "agent_item_context_status",
    ("agent_items", "context_override"): "jsonb",
    ("agent_items", "content"): "jsonb",
    ("post_embeddings", "embedding"): "vector(1536)",
    ("post_metrics", "status"): "post_metric_status",
    ("post_metrics", "execution_token"): "uuid",
}


def _insert(table: str, columns: tuple[str, ...], rows: list[dict[str, object]]) -> None:
    placeholders = ", ".join(
        f"CAST(:{column} AS {_COLUMN_CASTS[(table, column)]})"
        if (table, column) in _COLUMN_CASTS
        else f":{column}"
        for column in columns
    )
    names = ", ".join(columns)
    statement = sa.text(f"INSERT INTO {table} ({names}) VALUES ({placeholders})")  # noqa: S608
    _BIND.get().execute(statement, rows)


def _delete_ids(table: str, column: str, ids: tuple[int, ...]) -> None:
    statement = sa.text(f"DELETE FROM {table} WHERE {column} IN :ids").bindparams(  # noqa: S608
        sa.bindparam("ids", expanding=True)
    )
    _BIND.get().execute(statement, {"ids": ids})


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _request_hash(value: dict[str, object]) -> str:
    return _hash(_json(value))


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()


def _campaign_hash(campaign: dict[str, object]) -> str:
    search_text = "\n".join(
        (
            f"施策タイトル: {_normalize(str(campaign['title']))}",
            f"ターゲット像: {_normalize(str(campaign['target_profile']))}",
            f"実施背景: {_normalize(str(campaign['background']))}",
            f"施策目的: {_normalize(str(campaign['objective']))}",
            f"施策内容: {_normalize(str(campaign['plan']))}",
        )
    )
    return _hash(search_text)


def _vector(seed: int) -> str:
    values = [(((index * 13 + seed * 7) % 41) - 20) / 100 for index in range(1536)]
    return "[" + ",".join(f"{value:.2f}" for value in values) + "]"


def _tracked_url(post: dict[str, object], key: str) -> str:
    return (
        f"{post['landing_url']}?utm_source=x&utm_medium=social"
        f"&utm_campaign={post['campaign_id']}&utm_content={key}"
    )


def _pair_predicate(left: str, right: str, pairs: tuple[tuple[int, int], ...]) -> str:
    return " OR ".join(
        f"({left} = {left_id} AND {right} = {right_id})" for left_id, right_id in pairs
    )


def _preflight_upgrade() -> None:
    bind = _BIND.get()
    checks = {
        "companies.id": ("companies", "id", (_COMPANY_ID,)),
        "users.id": ("users", "id", (_USER_ID,)),
        "marketers.id": ("marketers", "id", (_MARKETER_ID,)),
        "campaigns.id": ("campaigns", "id", _CAMPAIGN_IDS),
        "agent_sessions.id": ("agent_sessions", "id", _SESSION_IDS),
        "agent_turns.id": ("agent_turns", "id", _TURN_IDS),
        "llm_calls.id": ("llm_calls", "id", _LLM_IDS),
        "agent_items.id": ("agent_items", "id", _ITEM_IDS),
        "api_idempotency_requests.id": ("api_idempotency_requests", "id", _REQUEST_IDS),
        "posts.id": ("posts", "id", _POST_IDS),
        "post_tracking_links.id": ("post_tracking_links", "id", _TRACKING_IDS),
        "agent_memories.id": ("agent_memories", "id", _MEMORY_IDS),
    }
    collisions: list[str] = []
    for label, (table, column, ids) in checks.items():
        statement = sa.text(
            f"SELECT EXISTS (SELECT 1 FROM {table} WHERE {column} IN :ids)"  # noqa: S608
        ).bindparams(sa.bindparam("ids", expanding=True))
        if bind.scalar(statement, {"ids": ids}):
            collisions.append(label)
    if bind.scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM users WHERE lower(email) = :email)"),
        {"email": _DEMO_EMAIL},
    ):
        collisions.append("users.email")
    if bind.scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM posts WHERE x_post_id IN :values)").bindparams(
            sa.bindparam("values", expanding=True)
        ),
        {"values": tuple(str(post["x_post_id"]) for post in _POSTS)},
    ):
        collisions.append("posts.x_post_id")
    if collisions:
        joined = ", ".join(collisions)
        raise RuntimeError(f"demo dataset conflicts with existing rows: {joined}")


def seed_demo() -> None:
    """Create a complete, login-capable demo tenant after collision checks."""
    _preflight_upgrade()
    created = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
    _insert(
        "companies",
        ("id", "name", "created_at", "updated_at"),
        [
            {
                "id": _COMPANY_ID,
                "name": "株式会社Hiromeruデモ",
                "created_at": created,
                "updated_at": created,
            }
        ],
    )
    _insert(
        "users",
        ("id", "email", "password", "created_at", "updated_at"),
        [
            {
                "id": _USER_ID,
                "email": _DEMO_EMAIL,
                "password": _PASSWORD_HASH,
                "created_at": created,
                "updated_at": created,
            }
        ],
    )
    _insert(
        "marketers",
        ("id", "user_id", "name", "company_id", "created_at", "updated_at"),
        [
            {
                "id": _MARKETER_ID,
                "user_id": _USER_ID,
                "name": "デモマーケター",
                "company_id": _COMPANY_ID,
                "created_at": created,
                "updated_at": created,
            }
        ],
    )
    _insert(
        "agent_memories",
        ("id", "company_id", "content", "embedding"),
        [
            {
                "id": memory_id,
                "company_id": _COMPANY_ID,
                "content": content,
                "embedding": _vector(20 + index),
            }
            for index, (memory_id, content) in enumerate(zip(_MEMORY_IDS, _MEMORIES, strict=True))
        ],
    )
    session_times = (
        (datetime(2026, 7, 14, 8, 0, tzinfo=UTC), datetime(2026, 7, 29, 6, 1, tzinfo=UTC)),
        (datetime(2026, 8, 10, 4, 0, tzinfo=UTC), datetime(2026, 8, 20, 3, 16, tzinfo=UTC)),
        (datetime(2026, 9, 12, 1, 0, tzinfo=UTC), datetime(2026, 9, 20, 1, 46, tzinfo=UTC)),
    )
    titles = ("経験者エンジニアの採用施策", "リモート採用投稿の作成", "公開結果の振り返り")
    _insert(
        "agent_sessions",
        (
            "id",
            "marketer_id",
            "parent_session_id",
            "agent",
            "title",
            "archived_at",
            "created_at",
            "updated_at",
        ),
        [
            {
                "id": session_id,
                "marketer_id": _MARKETER_ID,
                "parent_session_id": None,
                "agent": "parent",
                "title": titles[index],
                "archived_at": None,
                "created_at": times[0],
                "updated_at": times[1],
            }
            for index, (session_id, times) in enumerate(
                zip(_SESSION_IDS, session_times, strict=True)
            )
        ],
    )
    _insert(
        "campaigns",
        (
            "id",
            "company_id",
            "created_by_marketer_id",
            "title",
            "target_profile",
            "background",
            "objective",
            "plan",
            "created_at",
            "updated_at",
            "archived_at",
        ),
        [
            {
                **campaign,
                "company_id": _COMPANY_ID,
                "created_by_marketer_id": _MARKETER_ID,
                "updated_at": campaign["created_at"],
                "archived_at": None,
            }
            for campaign in _CAMPAIGNS
        ],
    )
    turn_specs = (
        (_TURN_IDS[0], _SESSION_IDS[0], 1, datetime(2026, 7, 14, 8, 0, tzinfo=UTC)),
        (_TURN_IDS[1], _SESSION_IDS[0], 2, datetime(2026, 7, 15, 2, 30, tzinfo=UTC)),
        (_TURN_IDS[2], _SESSION_IDS[0], 3, datetime(2026, 7, 29, 6, 0, tzinfo=UTC)),
        (_TURN_IDS[3], _SESSION_IDS[1], 1, datetime(2026, 8, 10, 4, 0, tzinfo=UTC)),
        (_TURN_IDS[4], _SESSION_IDS[1], 2, datetime(2026, 8, 20, 3, 15, tzinfo=UTC)),
        (_TURN_IDS[5], _SESSION_IDS[2], 1, datetime(2026, 9, 12, 1, 0, tzinfo=UTC)),
        (_TURN_IDS[6], _SESSION_IDS[2], 2, datetime(2026, 9, 20, 1, 45, tzinfo=UTC)),
    )
    _insert(
        "agent_turns",
        (
            "id",
            "session_id",
            "turn_number",
            "status",
            "next_item_number",
            "error_code",
            "error_message",
            "started_at",
            "completed_at",
            "created_at",
            "updated_at",
        ),
        [
            {
                "id": turn_id,
                "session_id": session_id,
                "turn_number": number,
                "status": "completed",
                "next_item_number": 3,
                "error_code": None,
                "error_message": None,
                "started_at": stamp,
                "completed_at": stamp + timedelta(minutes=1),
                "created_at": stamp,
                "updated_at": stamp + timedelta(minutes=1),
            }
            for turn_id, session_id, number, stamp in turn_specs
        ],
    )
    chat_turns = (_TURN_IDS[0], _TURN_IDS[3], _TURN_IDS[5])
    chat_turn_indexes = (0, 3, 5)
    _insert(
        "llm_calls",
        (
            "id",
            "agent_turn_id",
            "orcarouter_request_id",
            "input_tokens",
            "output_tokens",
            "cost_usd",
            "response_time_ms",
            "succeeded",
            "error_code",
            "error_message",
            "called_at",
        ),
        [
            {
                "id": _LLM_IDS[index],
                "agent_turn_id": turn_id,
                "orcarouter_request_id": f"demo-request-{index + 1}",
                "input_tokens": 120 + index * 10,
                "output_tokens": 48 + index * 5,
                "cost_usd": "0.00012000",
                "response_time_ms": 840 + index * 75,
                "succeeded": True,
                "error_code": None,
                "error_message": None,
                "called_at": turn_specs[chat_turn_indexes[index]][3] + timedelta(seconds=10),
            }
            for index, turn_id in enumerate(chat_turns)
        ],
    )
    _insert(
        "campaign_embeddings",
        ("campaign_id", "embedding", "content_hash", "created_at", "updated_at"),
        [
            {
                "campaign_id": campaign["id"],
                "embedding": _vector(index + 1),
                "content_hash": _campaign_hash(campaign),
                "created_at": campaign["created_at"],
                "updated_at": campaign["created_at"],
            }
            for index, campaign in enumerate(_CAMPAIGNS)
        ],
    )

    request_rows: list[dict[str, object]] = []
    for index, post in enumerate(_POSTS):
        key = _KEYS[index]
        turn_id = (_TURN_IDS[1], _TURN_IDS[2], _TURN_IDS[4], _TURN_IDS[6])[index]
        session_id = (_SESSION_IDS[0], _SESSION_IDS[0], _SESSION_IDS[1], _SESSION_IDS[2])[index]
        tracked_url = _tracked_url(post, key)
        request_body = {
            "campaign_id": post["campaign_id"],
            "body": post["body"],
            "landing_url": post["landing_url"],
        }
        completed_at = post["published_at"] + timedelta(minutes=1)
        response = {
            "success": True,
            "data": {
                "post_id": post["id"],
                "agent_turn_id": turn_id,
                "campaign_id": post["campaign_id"],
                "x_post_id": post["x_post_id"],
                "body": post["body"],
                "tracked_url": tracked_url,
                "published_at": post["published_at"].strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            "error": None,
        }
        external = {
            "x_post_id": post["x_post_id"],
            "text": f"{post['body']}\n{tracked_url}",
            "tracked_url": tracked_url,
            "published_at": post["published_at"].strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        request_rows.append(
            {
                "id": _REQUEST_IDS[index],
                "marketer_id": _MARKETER_ID,
                "session_id": session_id,
                "agent_turn_id": turn_id,
                "operation": "publish_x_post",
                "idempotency_key": key,
                "request_hash": _request_hash(request_body),
                "status": "succeeded",
                "execution_token": f"90030001-0000-4000-8000-{index + 1:012d}",
                "lease_expires_at": completed_at,
                "external_effect_started_at": post["published_at"],
                "external_result": _json(external),
                "http_status": 201,
                "response_body": _json(response),
                "created_at": post["published_at"],
                "updated_at": completed_at,
                "completed_at": completed_at,
            }
        )
    _insert(
        "api_idempotency_requests",
        (
            "id",
            "marketer_id",
            "session_id",
            "agent_turn_id",
            "operation",
            "idempotency_key",
            "request_hash",
            "status",
            "execution_token",
            "lease_expires_at",
            "external_effect_started_at",
            "external_result",
            "http_status",
            "response_body",
            "created_at",
            "updated_at",
            "completed_at",
        ),
        request_rows,
    )

    chat_text = (
        (
            "経験者エンジニア向けの採用施策を考えてください。",
            "働く一日を軸に、開発の進め方とチーム文化が具体的に伝わる施策を整理します。",
        ),
        (
            "フルリモートの働き方を伝える投稿を作りたいです。",
            "制度の説明だけでなく、相談方法や日々の連携が見える内容にすると安心感につながります。",
        ),
        (
            "公開済み投稿の結果を振り返ってください。",
            "具体的な仕事の流れを示した投稿は、制度中心の投稿より採用ページへの流入率が高い傾向です。",
        ),
    )
    item_rows: list[dict[str, object]] = []
    item_index = 0
    for chat_index, turn_id in enumerate(chat_turns):
        stamp = turn_specs[(0, 3, 5)[chat_index]][3]
        for number, (item_type, source, content) in enumerate(
            (
                ("user_message", "user_input", {"text": chat_text[chat_index][0]}),
                ("assistant_message", "agent_output", {"text": chat_text[chat_index][1]}),
            ),
            start=1,
        ):
            item_rows.append(
                {
                    "id": _ITEM_IDS[item_index],
                    "agent_turn_id": turn_id,
                    "related_tool_call_item_id": None,
                    "llm_call_id": _LLM_IDS[chat_index]
                    if item_type == "assistant_message"
                    else None,
                    "item_number": number,
                    "idempotency_key": f"demo-chat-{chat_index + 1}-{number}",
                    "item_type": item_type,
                    "context_class": "conversation",
                    "content_source": source,
                    "context_status": "active",
                    "quarantine_reason": None,
                    "context_override": None,
                    "quarantined_at": None,
                    "content": _json(content),
                    "created_at": stamp + timedelta(seconds=number * 20),
                }
            )
            item_index += 1
    approval_turns = (_TURN_IDS[1], _TURN_IDS[2], _TURN_IDS[4], _TURN_IDS[6])
    for index, (turn_id, post) in enumerate(zip(approval_turns, _POSTS, strict=True)):
        key = _KEYS[index]
        request_body = {
            "campaign_id": post["campaign_id"],
            "body": post["body"],
            "landing_url": post["landing_url"],
        }
        contents = (
            {"action": {"id": key, "type": "publish_x_post", "request": request_body}},
            {"kind": "api_result", "operation": "publish_x_post", "success": True, "error": None},
        )
        for number, content in enumerate(contents, start=1):
            item_rows.append(
                {
                    "id": _ITEM_IDS[item_index],
                    "agent_turn_id": turn_id,
                    "related_tool_call_item_id": None,
                    "llm_call_id": None,
                    "item_number": number,
                    "idempotency_key": f"approval-{'request' if number == 1 else 'result'}:{key}",
                    "item_type": "user_message" if number == 1 else "assistant_message",
                    "context_class": "conversation",
                    "content_source": "user_input" if number == 1 else "system",
                    "context_status": "active",
                    "quarantine_reason": None,
                    "context_override": None,
                    "quarantined_at": None,
                    "content": _json(content),
                    "created_at": post["published_at"] + timedelta(seconds=number * 20),
                }
            )
            item_index += 1
    _insert(
        "agent_items",
        (
            "id",
            "agent_turn_id",
            "related_tool_call_item_id",
            "llm_call_id",
            "item_number",
            "idempotency_key",
            "item_type",
            "context_class",
            "content_source",
            "context_status",
            "quarantine_reason",
            "context_override",
            "quarantined_at",
            "content",
            "created_at",
        ),
        item_rows,
    )
    _insert(
        "posts",
        (
            "id",
            "company_id",
            "created_by_marketer_id",
            "campaign_id",
            "api_idempotency_request_id",
            "body",
            "x_post_id",
            "published_at",
            "created_at",
            "updated_at",
        ),
        [
            {
                "id": post["id"],
                "company_id": _COMPANY_ID,
                "created_by_marketer_id": _MARKETER_ID,
                "campaign_id": post["campaign_id"],
                "api_idempotency_request_id": _REQUEST_IDS[index],
                "body": post["body"],
                "x_post_id": post["x_post_id"],
                "published_at": post["published_at"],
                "created_at": post["published_at"],
                "updated_at": post["published_at"],
            }
            for index, post in enumerate(_POSTS)
        ],
    )
    _insert(
        "post_embeddings",
        ("post_id", "embedding", "content_hash", "created_at"),
        [
            {
                "post_id": post["id"],
                "embedding": _vector(index + 10),
                "content_hash": _hash(_normalize(str(post["body"]))),
                "created_at": post["published_at"],
            }
            for index, post in enumerate(_POSTS)
        ],
    )
    _insert(
        "post_tracking_links",
        (
            "id",
            "post_id",
            "landing_url",
            "utm_source",
            "utm_medium",
            "utm_campaign",
            "utm_content",
            "tracked_url",
            "created_at",
            "updated_at",
        ),
        [
            {
                "id": _TRACKING_IDS[index],
                "post_id": post["id"],
                "landing_url": post["landing_url"],
                "utm_source": "x",
                "utm_medium": "social",
                "utm_campaign": str(post["campaign_id"]),
                "utm_content": _KEYS[index],
                "tracked_url": _tracked_url(post, _KEYS[index]),
                "created_at": post["published_at"],
                "updated_at": post["published_at"],
            }
            for index, post in enumerate(_POSTS)
        ],
    )
    _insert(
        "post_metrics",
        (
            "post_id",
            "scheduled_at",
            "status",
            "x_pv_count",
            "landing_user_count",
            "measured_at",
            "execution_token",
            "lease_expires_at",
            "attempt_count",
            "next_attempt_at",
            "last_error_code",
            "memory_generated_at",
            "memory_failed_at",
            "memory_attempt_count",
            "memory_next_attempt_at",
            "memory_last_error_code",
        ),
        [
            {
                "post_id": post["id"],
                "scheduled_at": post["published_at"] + timedelta(days=7),
                "status": "pending" if post["x_pv_count"] is None else "completed",
                "x_pv_count": post["x_pv_count"],
                "landing_user_count": post["landing_user_count"],
                "measured_at": None
                if post["x_pv_count"] is None
                else post["published_at"] + timedelta(days=7, minutes=5),
                "execution_token": None,
                "lease_expires_at": None,
                "attempt_count": 0 if post["x_pv_count"] is None else 1,
                "next_attempt_at": None,
                "last_error_code": None,
                "memory_generated_at": None
                if post["x_pv_count"] is None
                else post["published_at"] + timedelta(days=7, minutes=6),
                "memory_failed_at": None,
                "memory_attempt_count": 0,
                "memory_next_attempt_at": None,
                "memory_last_error_code": None,
            }
            for post in _POSTS
        ],
    )
    _insert(
        "memory_campaigns",
        ("memory_id", "campaign_id"),
        [
            {"memory_id": memory_id, "campaign_id": campaign_id}
            for memory_id, campaign_id in _MEMORY_CAMPAIGNS
        ],
    )
    _insert(
        "memory_posts",
        ("memory_id", "post_id"),
        [{"memory_id": memory_id, "post_id": post_id} for memory_id, post_id in _MEMORY_POSTS],
    )


def _has_non_seed_dependents() -> bool:
    bind = _BIND.get()
    params = {
        "company_id": _COMPANY_ID,
        "marketer_id": _MARKETER_ID,
        "campaign_ids": _CAMPAIGN_IDS,
        "session_ids": _SESSION_IDS,
        "turn_ids": _TURN_IDS,
        "llm_ids": _LLM_IDS,
        "item_ids": _ITEM_IDS,
        "request_ids": _REQUEST_IDS,
        "post_ids": _POST_IDS,
        "tracking_ids": _TRACKING_IDS,
        "memory_ids": _MEMORY_IDS,
    }
    checks = (
        "SELECT 1 FROM api_list_snapshots WHERE marketer_id = :marketer_id",
        "SELECT 1 FROM campaigns WHERE company_id = :company_id AND id NOT IN :campaign_ids",
        "SELECT 1 FROM agent_memories WHERE company_id = :company_id AND id NOT IN :memory_ids",
        "SELECT 1 FROM agent_sessions WHERE marketer_id = :marketer_id AND id NOT IN :session_ids",
        "SELECT 1 FROM agent_sessions WHERE parent_session_id IN :session_ids AND id NOT IN :session_ids",
        "SELECT 1 FROM agent_turns WHERE session_id IN :session_ids AND id NOT IN :turn_ids",
        "SELECT 1 FROM agent_items WHERE agent_turn_id IN :turn_ids AND id NOT IN :item_ids",
        "SELECT 1 FROM api_idempotency_requests WHERE marketer_id = :marketer_id AND id NOT IN :request_ids",
        "SELECT 1 FROM posts WHERE company_id = :company_id AND id NOT IN :post_ids",
        "SELECT 1 FROM post_tracking_links WHERE post_id IN :post_ids AND id NOT IN :tracking_ids",
        f"SELECT 1 FROM memory_campaigns WHERE (memory_id IN :memory_ids OR campaign_id IN :campaign_ids) AND NOT ({_pair_predicate('memory_id', 'campaign_id', _MEMORY_CAMPAIGNS)})",  # noqa: S608
        f"SELECT 1 FROM memory_posts WHERE (memory_id IN :memory_ids OR post_id IN :post_ids) AND NOT ({_pair_predicate('memory_id', 'post_id', _MEMORY_POSTS)})",  # noqa: S608
        "SELECT 1 FROM llm_calls WHERE agent_turn_id IN :turn_ids AND id NOT IN :llm_ids",
        "SELECT 1 FROM agent_context_checkpoints WHERE session_id IN :session_ids OR compacted_through_turn_id IN :turn_ids",
        "SELECT 1 FROM security_events WHERE agent_turn_id IN :turn_ids OR agent_item_id IN :item_ids",
        "SELECT 1 FROM tool_executions WHERE tool_call_item_id IN :item_ids",
    )
    for sql in checks:
        statement = sa.text(sql)
        for name in params:
            if f":{name}" in sql and name.endswith("_ids"):
                statement = statement.bindparams(sa.bindparam(name, expanding=True))
        if bind.execute(statement, params).first() is not None:
            return True
    return False


def remove_demo() -> None:
    """Delete only the fixed demo graph, refusing unsafe dependent-data removal."""
    if _has_non_seed_dependents():
        raise RuntimeError("demo dataset has non-seeded dependent rows; refusing unsafe downgrade")
    bind = _BIND.get()
    bind.execute(
        sa.text(
            "DELETE FROM memory_posts WHERE "  # noqa: S608
            + _pair_predicate("memory_id", "post_id", _MEMORY_POSTS)
        )
    )
    bind.execute(
        sa.text(
            "DELETE FROM memory_campaigns WHERE "  # noqa: S608
            + _pair_predicate("memory_id", "campaign_id", _MEMORY_CAMPAIGNS)
        )
    )
    _delete_ids("post_metrics", "post_id", _POST_IDS)
    _delete_ids("post_tracking_links", "id", _TRACKING_IDS)
    _delete_ids("post_embeddings", "post_id", _POST_IDS)
    _delete_ids("posts", "id", _POST_IDS)
    _delete_ids("campaign_embeddings", "campaign_id", _CAMPAIGN_IDS)
    _delete_ids("api_idempotency_requests", "id", _REQUEST_IDS)
    _delete_ids("agent_items", "id", _ITEM_IDS)
    _delete_ids("llm_calls", "id", _LLM_IDS)
    _delete_ids("agent_turns", "id", _TURN_IDS)
    _delete_ids("campaigns", "id", _CAMPAIGN_IDS)
    _delete_ids("agent_memories", "id", _MEMORY_IDS)
    _delete_ids("agent_sessions", "id", _SESSION_IDS)
    _delete_ids("marketers", "id", (_MARKETER_ID,))
    _delete_ids("users", "id", (_USER_ID,))
    _delete_ids("companies", "id", (_COMPANY_ID,))


def main() -> None:
    """Run the requested demo dataset operation in one transaction."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("seed", "remove"))
    args = parser.parse_args()
    settings = get_settings()
    engine = sa.create_engine(settings.sqlalchemy_url(settings.application_database_url()))
    with engine.begin() as connection:
        token = _BIND.set(connection)
        try:
            seed_demo() if args.action == "seed" else remove_demo()
        finally:
            _BIND.reset(token)
    engine.dispose()


if __name__ == "__main__":
    main()
