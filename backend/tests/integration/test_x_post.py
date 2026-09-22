import asyncio
import uuid
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from domain.tracking import build_tracking_url
from models import Post, PostMetric, PostTrackingLink
from repositories.database import SessionLocal
from repositories.posts import PostRepository
from tests.conftest import AccountFactory
from tests.support.client import Account, post_body
from tests.support.db import archive_campaign
from tests.support.fakes import FakeEmbedding, FakeXApi, FixedClock


async def _post_count(campaign_id: int) -> int:
    async with SessionLocal() as session:
        count = await session.scalar(
            select(func.count()).select_from(Post).where(Post.campaign_id == campaign_id)
        )
    return int(count or 0)


def _landing_url_for_tracked_length(target: int, campaign_id: int, key: str) -> str:
    prefix = "https://example.com/?q="
    base_length = len(build_tracking_url(prefix, campaign_id, key).tracked_url)
    assert target >= base_length
    return prefix + "a" * (target - base_length)


async def test_公開成功_正しい内容のとき201で投稿とUTM付きURLを返す(
    account: Account, x_api: FakeXApi
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)

    response = await account.publish_post(session_id, post_body(campaign_id))

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["campaign_id"] == campaign_id
    assert data["x_post_id"].startswith("x-")
    assert data["tracked_url"].startswith("https://example.com/lp?")
    assert "utm_source=x" in data["tracked_url"]
    assert x_api.calls == [f"{data['body']}\n{data['tracked_url']}"]


async def test_公開成功の保存内容_投稿とUTMと計測予定が作られる(
    account: Account, clock: FixedClock
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)

    response = await account.publish_post(session_id, post_body(campaign_id))

    post_id = response.json()["data"]["post_id"]
    async with SessionLocal() as session:
        link = (
            await session.execute(
                select(PostTrackingLink).where(PostTrackingLink.post_id == post_id)
            )
        ).scalar_one()
        metric = (
            await session.execute(select(PostMetric).where(PostMetric.post_id == post_id))
        ).scalar_one()
    assert link.landing_url == "https://example.com/lp"
    assert metric.status == "pending"
    assert (metric.scheduled_at - clock.now()).days == 7


async def test_本文の検証_本文にURLがあるとき422_INVALID_X_POSTでXを呼ばない(
    account: Account, x_api: FakeXApi
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)

    response = await account.publish_post(
        session_id, post_body(campaign_id, body="詳細は https://a.example.com へ")
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_X_POST"
    assert x_api.calls == []


async def test_文字数超過_URL込みで280を超えるとき422でXを呼ばない(
    account: Account, x_api: FakeXApi
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)

    response = await account.publish_post(session_id, post_body(campaign_id, body="あ" * 130))

    assert response.status_code == 422
    assert response.json()["error"]["field_errors"] == [
        {
            "field": None,
            "code": "X_LENGTH_EXCEEDED",
            "message": "投稿本文と遷移先URLの合計がXの文字数上限を超えています。",
        }
    ]
    assert x_api.calls == []


async def test_遷移先URL上限_UTM追加後が2048文字ちょうどなら投稿できる(
    account: Account, x_api: FakeXApi
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    key = str(uuid.uuid4())
    landing_url = _landing_url_for_tracked_length(2_048, campaign_id, key)

    response = await account.publish_post(
        session_id, post_body(campaign_id, landing_url=landing_url), key
    )

    assert response.status_code == 201
    assert len(response.json()["data"]["tracked_url"]) == 2_048
    assert len(x_api.calls) == 1


async def test_遷移先URL上限_UTM追加後が2049文字ならlanding_urlのErrorを返す(
    account: Account, x_api: FakeXApi
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    key = str(uuid.uuid4())
    landing_url = _landing_url_for_tracked_length(2_049, campaign_id, key)

    response = await account.publish_post(
        session_id, post_body(campaign_id, landing_url=landing_url), key
    )

    assert response.status_code == 422
    assert response.json()["error"]["field_errors"] == [
        {
            "field": "landing_url",
            "code": "TOO_LONG",
            "message": "UTM追加後の遷移先URLは2,048文字以内にしてください。",
        }
    ]
    assert x_api.calls == []


async def test_遷移先URL上限_入力が2049文字ならSchemaErrorでXを呼ばない(
    account: Account, x_api: FakeXApi
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    prefix = "https://example.com/"
    landing_url = prefix + "a" * (2_049 - len(prefix))

    response = await account.publish_post(
        session_id, post_body(campaign_id, landing_url=landing_url)
    )

    assert response.status_code == 400
    assert response.json()["error"]["field_errors"] == [
        {
            "field": "landing_url",
            "code": "TOO_LONG",
            "message": "遷移先URLは2,048文字以内で入力してください。",
        }
    ]
    assert x_api.calls == []


async def test_遷移先URL上限_入力が2048文字ちょうどなら受け付ける(
    account: Account, x_api: FakeXApi
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    prefix = "https://example.com/?utm_source="
    landing_url = prefix + "a" * (2_048 - len(prefix))

    response = await account.publish_post(
        session_id, post_body(campaign_id, landing_url=landing_url)
    )

    assert len(landing_url) == 2_048
    assert response.status_code == 201
    assert len(x_api.calls) == 1


async def test_Body検証_投稿本文が空のときbodyのFieldErrorを返す(account: Account) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)

    response = await account.publish_post(session_id, post_body(campaign_id, body="   "))

    assert response.status_code == 400
    assert response.json()["error"]["field_errors"] == [
        {"field": "body", "code": "REQUIRED", "message": "投稿本文を入力してください。"}
    ]


async def test_Body検証_NULを含む未知FieldもDB保存で500にせず400へ変換する(
    account: Account,
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    body = post_body(campaign_id)
    body["unknown\x00field"] = "value"

    response = await account.publish_post(session_id, body)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_ARGUMENT"
    assert response.json()["error"]["field_errors"][0]["field"] == "unknown[NUL]field"


async def test_遷移先URL不正_httpでもhttpsでもないとき422(account: Account) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)

    response = await account.publish_post(
        session_id, post_body(campaign_id, landing_url="javascript:alert(1)")
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "INVALID_X_POST"
    assert error["field_errors"][0]["code"] == "INVALID_URL"


@pytest.mark.parametrize(
    "landing_url",
    [
        "https://user@example.com/path",
        "https://user:password@example.com/path",
        "https://[::1/path",
        "https:///path",
        "https://example.com\\evil/path",
        "https://example.com%2Fevil/path",
        "https://example.com\x00/path",
        "https://./",
    ],
)
async def test_遷移先URL不正_UserInfoや不正Hostを422へ変換し外部Clientを呼ばない(
    account: Account,
    embedding: FakeEmbedding,
    x_api: FakeXApi,
    landing_url: str,
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    embedding.calls.clear()

    response = await account.publish_post(
        session_id, post_body(campaign_id, landing_url=landing_url)
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_X_POST"
    assert response.json()["error"]["field_errors"] == [
        {
            "field": "landing_url",
            "code": "INVALID_URL",
            "message": "遷移先URLが正しくありません。",
        }
    ]
    assert embedding.calls == []
    assert x_api.calls == []


async def test_投稿内容検証_本文とURLが不正なとき複数field_errorsを保存して再返却する(
    account: Account,
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    key = str(uuid.uuid4())
    body = post_body(
        campaign_id,
        body="詳細はhttps://example.comです",
        landing_url="https://user:password@example.com",
    )

    first = await account.publish_post(session_id, body, key)
    replay = await account.publish_post(session_id, body, key)

    assert first.status_code == 422
    assert first.json()["error"]["field_errors"] == [
        {
            "field": "body",
            "code": "INVALID_FORMAT",
            "message": "投稿本文にURLを含めることはできません。",
        },
        {
            "field": "landing_url",
            "code": "INVALID_URL",
            "message": "遷移先URLが正しくありません。",
        },
    ]
    assert replay.json() == first.json()


async def test_他社の施策_campaign_idが他社のとき404_CAMPAIGN_NOT_FOUNDでXを呼ばない(
    account: Account, new_account: AccountFactory, x_api: FakeXApi
) -> None:
    other = await new_account()
    other_campaign = await other.create_campaign()
    session_id = await account.create_session()

    response = await account.publish_post(session_id, post_body(other_campaign))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CAMPAIGN_NOT_FOUND"
    assert x_api.calls == []


async def test_Archive済みCampaignはEmbeddingとXを呼ばず409を同じキーで再返却する(
    account: Account,
    embedding: FakeEmbedding,
    x_api: FakeXApi,
    clock: FixedClock,
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    await archive_campaign(campaign_id, clock.now())
    embedding.calls.clear()
    key = str(uuid.uuid4())
    body = post_body(campaign_id)

    first = await account.publish_post(session_id, body, key)
    replay = await account.publish_post(session_id, body, key)

    assert first.status_code == 409
    assert first.json()["error"]["code"] == "CAMPAIGN_ARCHIVED"
    assert first.json()["error"]["retryable"] is False
    assert replay.json() == first.json()
    assert embedding.calls == []
    assert x_api.calls == []
    assert await _post_count(campaign_id) == 0


async def test_Embedding生成中にArchiveされたCampaignはXへ投稿しない(
    account: Account,
    embedding: FakeEmbedding,
    x_api: FakeXApi,
    clock: FixedClock,
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    embedding.calls.clear()
    gate = asyncio.Event()
    embedding.block_next = gate
    key = str(uuid.uuid4())
    body = post_body(campaign_id)
    running = asyncio.create_task(account.publish_post(session_id, body, key))
    await asyncio.wait_for(embedding.blocked.wait(), 5)
    await archive_campaign(campaign_id, clock.now())
    gate.set()

    response = await running
    replay = await account.publish_post(session_id, body, key)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CAMPAIGN_ARCHIVED"
    assert replay.json() == response.json()
    assert len(embedding.calls) == 1
    assert x_api.calls == []
    assert await _post_count(campaign_id) == 0


async def test_Embedding失敗_Xへ投稿する前に500_EMBEDDING_FAILEDで止まる(
    account: Account, embedding: FakeEmbedding, x_api: FakeXApi
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    embedding.fail = True

    response = await account.publish_post(session_id, post_body(campaign_id))

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "EMBEDDING_FAILED"
    assert x_api.calls == []


async def test_X拒否_403のとき502_X_POST_FAILEDで再試行不可(
    account: Account, x_api: FakeXApi
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    x_api.outcome = "rejected"

    response = await account.publish_post(session_id, post_body(campaign_id))

    assert response.status_code == 502
    error = response.json()["error"]
    assert error["code"] == "X_POST_FAILED"
    assert error["retryable"] is False
    assert await _post_count(campaign_id) == 0


async def test_X拒否_429のとき502で再試行可能(account: Account, x_api: FakeXApi) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    x_api.outcome, x_api.rejected_status = "rejected", 429

    response = await account.publish_post(session_id, post_body(campaign_id))

    assert response.status_code == 502
    assert response.json()["error"]["retryable"] is True


async def test_結果不明_Xの結果を確定できないとき504で保存済み応答を再返却し再投稿しない(
    account: Account, x_api: FakeXApi
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    x_api.outcome = "unknown"
    key = str(uuid.uuid4())
    first = await account.publish_post(session_id, post_body(campaign_id), key)
    x_api.outcome = "ok"

    second = await account.publish_post(session_id, post_body(campaign_id), key)

    assert first.status_code == second.status_code == 504
    assert second.json() == first.json()
    assert first.json()["error"]["code"] == "X_POST_OUTCOME_UNKNOWN"
    assert len(x_api.calls) == 1
    assert await _post_count(campaign_id) == 0


async def test_結果不明_X送信開始後に想定外の例外が起きても再投稿可能な内部Errorにしない(
    account: Account, x_api: FakeXApi
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    x_api.outcome = "unexpected"
    key = str(uuid.uuid4())

    first = await account.publish_post(session_id, post_body(campaign_id), key)
    second = await account.publish_post(session_id, post_body(campaign_id), key)

    assert first.status_code == second.status_code == 504
    assert first.json()["error"]["code"] == "X_POST_OUTCOME_UNKNOWN"
    assert first.json()["error"]["retryable"] is False
    assert second.json() == first.json()
    assert len(x_api.calls) == 1


async def test_冪等性_成功後に同じキーで再送しても同じ応答でXへ再投稿しない(
    account: Account, x_api: FakeXApi
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    key = str(uuid.uuid4())
    first = await account.publish_post(session_id, post_body(campaign_id), key)

    second = await account.publish_post(session_id, post_body(campaign_id), key)

    assert second.status_code == first.status_code == 201
    assert second.json() == first.json()
    assert len(x_api.calls) == 1
    assert await _post_count(campaign_id) == 1


async def test_処理中_同じキーの同時Requestのとき409_IN_PROGRESSとRetry_After(
    account: Account, x_api: FakeXApi
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    x_api.gate = asyncio.Event()
    key = str(uuid.uuid4())
    running = asyncio.create_task(account.publish_post(session_id, post_body(campaign_id), key))
    await asyncio.wait_for(x_api.started.wait(), 5)

    concurrent = await account.publish_post(session_id, post_body(campaign_id), key)
    x_api.gate.set()
    finished = await running

    assert concurrent.status_code == 409
    assert concurrent.json()["error"]["code"] == "IDEMPOTENCY_REQUEST_IN_PROGRESS"
    assert concurrent.headers["retry-after"] == "5"
    assert finished.status_code == 201
    assert len(x_api.calls) == 1


async def test_未確定の重複_別キーで同じ内容が処理中のとき409_X_POST_UNRESOLVED(
    account: Account, x_api: FakeXApi
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    x_api.gate = asyncio.Event()
    running = asyncio.create_task(account.publish_post(session_id, post_body(campaign_id)))
    await asyncio.wait_for(x_api.started.wait(), 5)

    duplicate = await account.publish_post(session_id, post_body(campaign_id))
    x_api.gate.set()
    await running

    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "X_POST_UNRESOLVED"
    assert len(x_api.calls) == 1


async def test_Lease失効後の復旧_X送信後に結果を保存できないまま失効したとき504へ確定する(
    account: Account, x_api: FakeXApi, clock: FixedClock
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    x_api.gate = asyncio.Event()
    key = str(uuid.uuid4())
    running = asyncio.create_task(account.publish_post(session_id, post_body(campaign_id), key))
    await asyncio.wait_for(x_api.started.wait(), 5)
    clock.advance(331)

    recovered = await account.publish_post(session_id, post_body(campaign_id), key)
    x_api.gate.set()
    await running

    assert recovered.status_code == 504
    assert recovered.json()["error"]["code"] == "X_POST_OUTCOME_UNKNOWN"
    replay = await account.publish_post(session_id, post_body(campaign_id), key)
    assert replay.status_code == 504
    assert len(x_api.calls) == 1


async def test_DB保存失敗からの再開_X投稿成功後の保存が失敗しても同じキーの再送で再投稿せず保存する(
    account: Account, x_api: FakeXApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    key = str(uuid.uuid4())
    original = PostRepository.insert_published

    async def failing(self: PostRepository, *args: Any, **kwargs: Any) -> Any:
        raise OperationalError("INSERT", {}, Exception("db down"))

    monkeypatch.setattr(PostRepository, "insert_published", failing)
    failed = await account.publish_post(session_id, post_body(campaign_id), key)
    monkeypatch.setattr(PostRepository, "insert_published", original)

    resumed = await account.publish_post(session_id, post_body(campaign_id), key)

    assert failed.status_code == 500
    assert failed.json()["error"]["code"] == "X_POST_SAVE_FAILED"
    assert failed.json()["error"]["retryable"] is True
    assert resumed.status_code == 201
    assert len(x_api.calls) == 1
    assert await _post_count(campaign_id) == 1
