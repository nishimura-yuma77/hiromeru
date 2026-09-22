from datetime import datetime
from urllib.parse import quote

from sqlalchemy import select, update

from domain.enums import ApiIdempotencyStatus
from models import ApiIdempotencyRequest, Post
from repositories.database import SessionLocal
from tests.conftest import AccountFactory
from tests.support.client import Account, post_body
from tests.support.db import archive_campaign, insert_memory
from tests.support.fakes import FixedClock


async def _publish(
    account: Account, session_id: int, campaign_id: int, body: str, clock: FixedClock
) -> int:
    clock.advance(60)
    response = await account.publish_post(session_id, post_body(campaign_id, body=body))
    assert response.status_code == 201, response.text
    return int(response.json()["data"]["post_id"])


async def _set_publication(
    post_id: int, status: ApiIdempotencyStatus, *, published_at: datetime | None = None
) -> None:
    async with SessionLocal() as session, session.begin():
        request_id = (
            await session.execute(select(Post.api_idempotency_request_id).where(Post.id == post_id))
        ).scalar_one()
        values: dict[str, object] = {"status": status}
        if status == ApiIdempotencyStatus.PROCESSING:
            values.update(http_status=None, response_body=None, completed_at=None)
        await session.execute(
            update(ApiIdempotencyRequest)
            .where(ApiIdempotencyRequest.id == request_id)
            .values(**values)
        )
        if published_at is not None:
            await session.execute(
                update(Post).where(Post.id == post_id).values(published_at=published_at)
            )


async def test_記憶一覧_campaign_id指定が通常一覧と意味検索へ適用される(account: Account) -> None:
    campaign_a = await account.create_campaign(title="A")
    campaign_b = await account.create_campaign(title="B")
    target = await insert_memory(
        account.company_id, "朝の投稿は反応が良い", campaign_ids=(campaign_a,)
    )
    await insert_memory(account.company_id, "朝とは無関係", campaign_ids=(campaign_b,))

    recent = await account.client.get(f"/api/v1/memories?campaign_id={campaign_a}")
    semantic = await account.client.get(
        f"/api/v1/memories?campaign_id={campaign_a}&query={quote('朝の投稿は反応が良い')}"
    )

    assert [item["id"] for item in recent.json()["data"]["memories"]] == [target]
    assert [item["id"] for item in semantic.json()["data"]["memories"]] == [target]
    assert semantic.json()["data"]["memories"][0]["similarity"] > 0.99


async def test_記憶一覧_campaign_idが別会社またはcursorと異なるとき拒否する(
    account: Account, new_account: AccountFactory
) -> None:
    campaign_a = await account.create_campaign(title="A")
    campaign_b = await account.create_campaign(title="B")
    for number in range(2):
        await insert_memory(
            account.company_id, f"記憶{number}", campaign_ids=(campaign_a, campaign_b)
        )
    page = (await account.client.get(f"/api/v1/memories?campaign_id={campaign_a}&limit=1")).json()[
        "data"
    ]
    misuse = await account.client.get(
        f"/api/v1/memories?campaign_id={campaign_b}&limit=1&cursor={quote(page['next_cursor'])}"
    )
    missing = await account.client.get("/api/v1/memories?campaign_id=999999999")
    other = await new_account()
    other_campaign = await other.create_campaign()
    cross_tenant = await account.client.get(f"/api/v1/memories?campaign_id={other_campaign}")

    assert misuse.status_code == 400
    assert misuse.json()["error"]["code"] == "INVALID_ARGUMENT"
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "CAMPAIGN_NOT_FOUND"
    assert cross_tenant.status_code == 404
    assert cross_tenant.json()["error"]["code"] == "CAMPAIGN_NOT_FOUND"


async def test_記憶関連施策_4件あるときArchive状態付きで3件と続きを返す(
    account: Account, clock: FixedClock
) -> None:
    campaign_ids = [await account.create_campaign(title=f"施策{number}") for number in range(4)]
    await archive_campaign(campaign_ids[0], clock.now())
    memory_id = await insert_memory(
        account.company_id, "施策が4件ある記憶", campaign_ids=tuple(campaign_ids)
    )

    card = (await account.client.get("/api/v1/memories")).json()["data"]["memories"][0]
    continuation = (
        await account.client.get(
            f"/api/v1/memories/{memory_id}/campaigns?cursor={quote(card['campaigns_next_cursor'])}"
        )
    ).json()["data"]
    first_page = (
        await account.client.get(f"/api/v1/memories/{memory_id}/campaigns?limit=2")
    ).json()["data"]
    second_page = (
        await account.client.get(
            f"/api/v1/memories/{memory_id}/campaigns?limit=2"
            f"&cursor={quote(first_page['next_cursor'])}"
        )
    ).json()["data"]

    assert [item["id"] for item in card["campaigns"]] == campaign_ids[:0:-1]
    assert card["campaigns_next_cursor"] is not None
    assert [item["id"] for item in continuation["campaigns"]] == [campaign_ids[0]]
    assert continuation["campaigns"][0]["archived_at"] is not None
    assert [item["id"] for item in first_page["campaigns"] + second_page["campaigns"]] == list(
        reversed(campaign_ids)
    )
    assert second_page["next_cursor"] is None


async def test_記憶関連投稿_公開成功だけを同一日時のid降順で返し続きも取得できる(
    account: Account, clock: FixedClock
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    post_ids = [
        await _publish(account, session_id, campaign_id, f"投稿{number}", clock)
        for number in range(7)
    ]
    same_time = clock.now()
    for post_id in post_ids[:4]:
        await _set_publication(post_id, ApiIdempotencyStatus.SUCCEEDED, published_at=same_time)
    for post_id, status in zip(
        post_ids[4:],
        (
            ApiIdempotencyStatus.FAILED,
            ApiIdempotencyStatus.PROCESSING,
            ApiIdempotencyStatus.OUTCOME_UNKNOWN,
        ),
        strict=True,
    ):
        await _set_publication(post_id, status)
    memory_id = await insert_memory(account.company_id, "投稿境界の記憶", post_ids=tuple(post_ids))

    card = (await account.client.get("/api/v1/memories")).json()["data"]["memories"][0]
    continuation = (
        await account.client.get(
            f"/api/v1/memories/{memory_id}/posts?cursor={quote(card['posts_next_cursor'])}"
        )
    ).json()["data"]

    assert [item["post_id"] for item in card["posts"]] == list(reversed(post_ids[1:4]))
    assert [item["post_id"] for item in continuation["posts"]] == [post_ids[0]]
    assert continuation["next_cursor"] is None


async def test_記憶関連一覧_memory_idとEndpointがcursorと異なるとき拒否する(
    account: Account, new_account: AccountFactory
) -> None:
    campaign_ids = [await account.create_campaign(title=f"施策{number}") for number in range(4)]
    memory_a = await insert_memory(account.company_id, "記憶A", campaign_ids=tuple(campaign_ids))
    memory_b = await insert_memory(account.company_id, "記憶B")
    card = (await account.client.get("/api/v1/memories")).json()["data"]["memories"]
    memory_a_card = next(item for item in card if item["id"] == memory_a)
    cursor = memory_a_card["campaigns_next_cursor"]

    wrong_memory = await account.client.get(
        f"/api/v1/memories/{memory_b}/campaigns?cursor={quote(cursor)}"
    )
    wrong_endpoint = await account.client.get(
        f"/api/v1/memories/{memory_a}/posts?cursor={quote(cursor)}"
    )
    other = await new_account()
    other_memory = await insert_memory(other.company_id, "他社の記憶")
    cross_tenant = await account.client.get(f"/api/v1/memories/{other_memory}/campaigns")
    missing = await account.client.get("/api/v1/memories/999999999/posts")

    assert wrong_memory.status_code == 400
    assert wrong_endpoint.status_code == 400
    assert cross_tenant.status_code == 404
    assert cross_tenant.json()["error"]["code"] == "MEMORY_NOT_FOUND"
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "MEMORY_NOT_FOUND"


async def test_記憶関連一覧_関連なしとlimit境界を正しく扱う(account: Account) -> None:
    memory_id = await insert_memory(account.company_id, "関連なし")

    card = (await account.client.get("/api/v1/memories")).json()["data"]["memories"][0]
    campaigns = await account.client.get(f"/api/v1/memories/{memory_id}/campaigns")
    posts = await account.client.get(f"/api/v1/memories/{memory_id}/posts")
    too_small = await account.client.get(f"/api/v1/memories/{memory_id}/campaigns?limit=0")
    too_large = await account.client.get(f"/api/v1/memories/{memory_id}/posts?limit=51")

    assert card["campaigns"] == []
    assert card["campaigns_next_cursor"] is None
    assert card["posts"] == []
    assert card["posts_next_cursor"] is None
    assert campaigns.json()["data"] == {"campaigns": [], "next_cursor": None}
    assert posts.json()["data"] == {"posts": [], "next_cursor": None}
    assert too_small.status_code == 400
    assert too_large.status_code == 400
