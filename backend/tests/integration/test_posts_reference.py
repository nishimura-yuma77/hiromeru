from urllib.parse import quote

from httpx import AsyncClient

from domain.search_text import build_post_search_text
from tests.conftest import AccountFactory
from tests.support.client import Account, post_body
from tests.support.db import archive_campaign, complete_metrics, insert_memory
from tests.support.fakes import FixedClock


async def _publish(
    account: Account, session_id: int, campaign_id: int, body: str, clock: FixedClock
) -> int:
    clock.advance(60)
    response = await account.publish_post(session_id, post_body(campaign_id, body=body))
    assert response.status_code == 201, response.text
    return int(response.json()["data"]["post_id"])


async def test_一覧_公開日時の降順が既定で他社の投稿を含めない(
    account: Account, new_account: AccountFactory, clock: FixedClock
) -> None:
    other = await new_account()
    other_session = await other.create_session()
    other_campaign = await other.create_campaign(other_session)
    await _publish(other, other_session, other_campaign, "他社の投稿", clock)
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    first = await _publish(account, session_id, campaign_id, "1件目の投稿", clock)
    second = await _publish(account, session_id, campaign_id, "2件目の投稿", clock)

    response = await account.client.get("/api/v1/posts")

    assert response.status_code == 200
    posts = response.json()["data"]["posts"]
    assert [p["post_id"] for p in posts] == [second, first]
    assert posts[0]["campaign_id"] == campaign_id
    assert posts[0]["campaign_archived_at"] is None
    assert posts[0]["metrics"]["status"] == "pending"
    assert posts[0]["similarity"] is None


async def test_一覧のページング_公開日時のkeysetで重複なく取得できる(
    account: Account, clock: FixedClock
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    ids = [await _publish(account, session_id, campaign_id, f"投稿{n}", clock) for n in range(3)]

    page1 = (await account.client.get("/api/v1/posts?limit=2")).json()["data"]
    page2 = (
        await account.client.get(f"/api/v1/posts?limit=2&cursor={quote(page1['next_cursor'])}")
    ).json()["data"]

    assert [p["post_id"] for p in page1["posts"]] == [ids[2], ids[1]]
    assert [p["post_id"] for p in page2["posts"]] == [ids[0]]
    assert page2["next_cursor"] is None


async def test_PV順の並び替え_未計測をnullsLastにしkeysetで続きを取得できる(
    account: Account, clock: FixedClock
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    low = await _publish(account, session_id, campaign_id, "低PV", clock)
    high = await _publish(account, session_id, campaign_id, "高PV", clock)
    unmeasured = await _publish(account, session_id, campaign_id, "未計測", clock)
    await complete_metrics(low, x_pv_count=10, landing_user_count=1)
    await complete_metrics(high, x_pv_count=500, landing_user_count=5)

    page1 = (await account.client.get("/api/v1/posts?sort=x_pv_count&order=desc&limit=2")).json()[
        "data"
    ]
    page2 = (
        await account.client.get(
            f"/api/v1/posts?sort=x_pv_count&order=desc&limit=2&cursor={quote(page1['next_cursor'])}"
        )
    ).json()["data"]

    assert [p["post_id"] for p in page1["posts"]] == [high, low]
    assert [p["post_id"] for p in page2["posts"]] == [unmeasured]


async def test_並び替えの指定不正_sortが未定義のとき400(account: Account) -> None:
    response = await account.client.get("/api/v1/posts?sort=unknown")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_ARGUMENT"


async def test_カーソルの取り違え_別の並び順のcursorのとき400(
    account: Account, clock: FixedClock
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    for n in range(2):
        await _publish(account, session_id, campaign_id, f"投稿{n}", clock)
    page = (await account.client.get("/api/v1/posts?limit=1")).json()["data"]

    response = await account.client.get(
        f"/api/v1/posts?sort=x_pv_count&limit=1&cursor={quote(page['next_cursor'])}"
    )

    assert response.status_code == 400


async def test_施策での絞り込み_campaign_idを指定したとき該当施策の投稿だけを返す(
    account: Account, clock: FixedClock
) -> None:
    session_id = await account.create_session()
    campaign_a = await account.create_campaign(session_id, title="A")
    campaign_b = await account.create_campaign(session_id, title="B")
    post_a = await _publish(account, session_id, campaign_a, "Aの投稿", clock)
    await _publish(account, session_id, campaign_b, "Bの投稿", clock)

    response = await account.client.get(f"/api/v1/posts?campaign_id={campaign_a}")

    assert [p["post_id"] for p in response.json()["data"]["posts"]] == [post_a]


async def test_意味検索_queryに近い投稿がsimilarity付きで先頭に来る(
    account: Account, clock: FixedClock
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    target = await _publish(account, session_id, campaign_id, "検索されたい投稿", clock)
    await _publish(account, session_id, campaign_id, "関係のない投稿", clock)

    response = await account.client.get(
        f"/api/v1/posts?query={quote(build_post_search_text('検索されたい投稿'))}"
    )

    posts = response.json()["data"]["posts"]
    assert posts[0]["post_id"] == target
    assert posts[0]["similarity"] > 0.99


async def test_公開範囲の指定_published_toより後の投稿を含めない(
    account: Account, clock: FixedClock
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    old = await _publish(account, session_id, campaign_id, "古い投稿", clock)
    clock.advance(30)
    boundary = clock.now().isoformat().replace("+00:00", "Z")
    clock.advance(3600)
    await _publish(account, session_id, campaign_id, "新しい投稿", clock)

    response = await account.client.get(f"/api/v1/posts?published_to={quote(boundary)}")

    assert [p["post_id"] for p in response.json()["data"]["posts"]] == [old]


async def test_詳細_UTM付きURLと計測状況と施策を返す(account: Account, clock: FixedClock) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    post_id = await _publish(account, session_id, campaign_id, "詳細の投稿", clock)

    response = await account.client.get(f"/api/v1/posts/{post_id}")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["post"]["body"] == "詳細の投稿"
    assert data["campaign"]["id"] == campaign_id
    assert data["campaign"]["archived_at"] is None
    assert data["tracking"]["landing_url"] == "https://example.com/lp"
    assert data["tracking"]["tracked_url"].startswith("https://example.com/lp?")
    assert data["metrics"]["status"] == "pending"


async def test_Archive済み施策の投稿と計測と記憶を各参照結果に保持する(
    account: Account, clock: FixedClock
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    post_id = await _publish(account, session_id, campaign_id, "Archive前の投稿", clock)
    await complete_metrics(post_id, x_pv_count=100, landing_user_count=20)
    memory_id = await insert_memory(
        account.company_id,
        "Archive前の記憶",
        campaign_ids=(campaign_id,),
        post_ids=(post_id,),
    )
    archived_at = clock.now().isoformat().replace("+00:00", "Z")
    await archive_campaign(campaign_id, clock.now())

    post_list = (await account.client.get("/api/v1/posts")).json()["data"]["posts"]
    post_detail = (await account.client.get(f"/api/v1/posts/{post_id}")).json()["data"]
    metrics = (await account.client.get("/api/v1/metrics")).json()["data"]
    memories = (await account.client.get("/api/v1/memories")).json()["data"]["memories"]

    assert [post["post_id"] for post in post_list] == [post_id]
    assert post_list[0]["campaign_archived_at"] == archived_at
    assert post_detail["campaign"]["archived_at"] == archived_at
    assert metrics["summary"]["post_count"] == 1
    assert metrics["campaigns"][0]["id"] == campaign_id
    assert metrics["campaigns"][0]["archived_at"] == archived_at
    assert [memory["id"] for memory in memories] == [memory_id]
    assert memories[0]["campaigns"] == [
        {
            "id": campaign_id,
            "title": "春の新規フォロワー獲得",
            "archived_at": archived_at,
        }
    ]
    assert memories[0]["posts"][0]["post_id"] == post_id


async def test_詳細_他社の投稿のとき404_POST_NOT_FOUND(
    account: Account, new_account: AccountFactory, clock: FixedClock
) -> None:
    other = await new_account()
    other_session = await other.create_session()
    other_post = await _publish(
        other, other_session, await other.create_campaign(other_session), "他社", clock
    )

    response = await account.client.get(f"/api/v1/posts/{other_post}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "POST_NOT_FOUND"


async def test_未公開の投稿は見えない_X投稿が失敗した候補は一覧にも詳細にも出ない(
    account: Account,
) -> None:
    campaign_id = await account.create_campaign()

    response = await account.client.get(f"/api/v1/posts?campaign_id={campaign_id}")

    assert response.json()["data"]["posts"] == []


async def test_計測結果集計_期間内の完了件数とlanding_rateを施策別に返す(
    account: Account, clock: FixedClock
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    first = await _publish(account, session_id, campaign_id, "計測1", clock)
    second = await _publish(account, session_id, campaign_id, "計測2", clock)
    await _publish(account, session_id, campaign_id, "未計測", clock)
    await complete_metrics(first, x_pv_count=100, landing_user_count=10)
    await complete_metrics(second, x_pv_count=100, landing_user_count=30)

    response = await account.client.get("/api/v1/metrics")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["summary"]["post_count"] == 3
    assert data["summary"]["completed_count"] == 2
    assert data["summary"]["pending_count"] == 1
    assert data["summary"]["x_pv_count"] == 200
    assert data["summary"]["landing_rate"] == 0.2
    assert data["campaigns"][0]["id"] == campaign_id
    assert data["campaigns"][0]["archived_at"] is None


async def test_計測結果集計_投稿がないとき0件でlanding_rateはnull(account: Account) -> None:
    response = await account.client.get("/api/v1/metrics")

    summary = response.json()["data"]["summary"]
    assert summary["post_count"] == 0
    assert summary["landing_rate"] is None


async def test_記憶一覧_自社の記憶だけを関連付きで返す(
    account: Account, new_account: AccountFactory
) -> None:
    other = await new_account()
    await insert_memory(other.company_id, "他社の記憶")
    campaign_id = await account.create_campaign()
    mine = await insert_memory(account.company_id, "自社の記憶", campaign_ids=(campaign_id,))

    response = await account.client.get("/api/v1/memories")

    memories = response.json()["data"]["memories"]
    assert [m["id"] for m in memories] == [mine]
    assert memories[0]["campaigns"][0]["id"] == campaign_id
    assert memories[0]["campaigns"][0]["archived_at"] is None
    assert memories[0]["similarity"] is None


async def test_記憶の意味検索_queryが一致する記憶が先頭に来る(account: Account) -> None:
    await insert_memory(account.company_id, "無関係な記憶")
    target = await insert_memory(account.company_id, "朝の投稿は反応が良い")

    response = await account.client.get(f"/api/v1/memories?query={quote('朝の投稿は反応が良い')}")

    memories = response.json()["data"]["memories"]
    assert memories[0]["id"] == target
    assert memories[0]["similarity"] > 0.99


async def test_記憶の削除_自社の記憶のとき200で削除され再削除は404(account: Account) -> None:
    memory_id = await insert_memory(account.company_id, "消す記憶")

    deleted = await account.client.delete(f"/api/v1/memories/{memory_id}")
    again = await account.client.delete(f"/api/v1/memories/{memory_id}")

    assert deleted.status_code == 200
    assert deleted.json()["data"] == {"memory_id": memory_id, "deleted": True}
    assert again.status_code == 404
    assert again.json()["error"]["code"] == "MEMORY_NOT_FOUND"


async def test_記憶の削除_他社の記憶のとき404で削除されない(
    account: Account, new_account: AccountFactory
) -> None:
    other = await new_account()
    memory_id = await insert_memory(other.company_id, "他社の記憶")

    response = await account.client.delete(f"/api/v1/memories/{memory_id}")

    assert response.status_code == 404
    still = await other.client.get("/api/v1/memories")
    assert [m["id"] for m in still.json()["data"]["memories"]] == [memory_id]


async def test_記憶の削除_CSRFトークンがないとき403(
    account: Account, anonymous: AsyncClient
) -> None:
    del anonymous
    memory_id = await insert_memory(account.company_id, "消えない記憶")
    account.client.headers.pop("X-CSRF-Token")

    response = await account.client.delete(f"/api/v1/memories/{memory_id}")

    assert response.status_code == 403
