from urllib.parse import quote

import pytest
from httpx import AsyncClient

from domain.campaign_rules import CampaignContent
from domain.constants import EMBEDDING_DIMENSIONS
from domain.search_text import build_campaign_search_text
from tests.conftest import AccountFactory
from tests.support.client import Account, campaign_body, post_body
from tests.support.db import archive_campaign, complete_metrics, insert_memory
from tests.support.fakes import FakeEmbedding, FixedClock


async def test_一覧_作成順の降順で返し他社の施策を含めない(
    account: Account, new_account: AccountFactory
) -> None:
    other = await new_account()
    await other.create_campaign(title="他社の施策")
    session_id = await account.create_session()
    first = await account.create_campaign(session_id, title="1件目")
    second = await account.create_campaign(session_id, title="2件目")

    response = await account.client.get("/api/v1/campaigns")

    assert response.status_code == 200
    campaigns = response.json()["data"]["campaigns"]
    assert [c["id"] for c in campaigns] == [second, first]
    assert campaigns[0]["similarity"] is None
    assert campaigns[0]["metrics_summary"]["post_count"] == 0
    assert campaigns[0]["metrics_summary"]["landing_rate"] is None


@pytest.mark.parametrize("query", [None, "施策"])
@pytest.mark.parametrize(
    ("archived", "expected_titles"),
    [
        (None, {"有効な施策", "Archive済み施策"}),
        (False, {"有効な施策"}),
        (True, {"Archive済み施策"}),
    ],
)
async def test_一覧_archivedの3状態が通常一覧と意味検索で同じように動く(
    account: Account,
    clock: FixedClock,
    query: str | None,
    archived: bool | None,
    expected_titles: set[str],
) -> None:
    session_id = await account.create_session()
    await account.create_campaign(session_id, title="有効な施策")
    archived_id = await account.create_campaign(session_id, title="Archive済み施策")
    archived_at = clock.now().isoformat().replace("+00:00", "Z")
    await archive_campaign(archived_id, clock.now())
    params: dict[str, str | bool] = {}
    if query is not None:
        params["query"] = query
    if archived is not None:
        params["archived"] = archived

    response = await account.client.get("/api/v1/campaigns", params=params)

    assert response.status_code == 200
    campaigns = response.json()["data"]["campaigns"]
    assert {campaign["title"] for campaign in campaigns} == expected_titles
    assert {campaign["title"]: campaign["archived_at"] for campaign in campaigns} == {
        title: archived_at if title == "Archive済み施策" else None for title in expected_titles
    }
    assert all(
        (campaign["similarity"] is not None) == (query is not None) for campaign in campaigns
    )


async def test_一覧のページング_limitで区切りnext_cursorで続きを取得できる(
    account: Account,
) -> None:
    session_id = await account.create_session()
    ids = [await account.create_campaign(session_id, title=f"施策{n}") for n in range(3)]

    page1 = (await account.client.get("/api/v1/campaigns?limit=2")).json()["data"]
    page2 = (
        await account.client.get(f"/api/v1/campaigns?limit=2&cursor={quote(page1['next_cursor'])}")
    ).json()["data"]

    assert [c["id"] for c in page1["campaigns"]] == [ids[2], ids[1]]
    assert [c["id"] for c in page2["campaigns"]] == [ids[0]]
    assert page2["next_cursor"] is None


async def test_カーソル不正_壊れたcursorのとき400_INVALID_ARGUMENT(account: Account) -> None:
    response = await account.client.get("/api/v1/campaigns?cursor=broken")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_ARGUMENT"


async def test_意味検索_queryがあるとき類似度の高い順でsimilarityを返す(
    account: Account,
) -> None:
    session_id = await account.create_session()
    target = campaign_body(title="検索対象", objective="独自の目的A")
    other = campaign_body(title="別の施策", objective="まったく違う目的B")
    target_id = await account.create_campaign(session_id, **target)
    await account.create_campaign(session_id, **other)
    query = build_campaign_search_text(
        CampaignContent(
            target["title"],
            target["target_profile"],
            target["background"],
            target["objective"],
            target["plan"],
        )
    )

    response = await account.client.get(f"/api/v1/campaigns?query={quote(query)}")

    assert response.status_code == 200
    campaigns = response.json()["data"]["campaigns"]
    assert campaigns[0]["id"] == target_id
    assert campaigns[0]["similarity"] > 0.99
    assert campaigns[0]["similarity"] >= campaigns[1]["similarity"]


async def test_意味検索_タイトルだけの検索で対象施策を取得できる(
    account: Account, embedding: FakeEmbedding, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = "タイトルだけで見つかる採用施策"

    async def semantic_embedding(text: str) -> list[float]:
        embedding.calls.append(text)
        vector = [0.0] * EMBEDDING_DIMENSIONS
        vector[0 if marker in text else 1] = 1.0
        return vector

    monkeypatch.setattr(embedding, "embed", semantic_embedding)
    session_id = await account.create_session()
    target_id = await account.create_campaign(session_id, title=marker)
    await account.create_campaign(session_id, title="別の施策")

    response = await account.client.get(f"/api/v1/campaigns?query={quote(marker)}")

    assert response.status_code == 200
    assert response.json()["data"]["campaigns"][0]["id"] == target_id


async def test_日付範囲の指定不正_タイムゾーンがないとき400(account: Account) -> None:
    response = await account.client.get("/api/v1/campaigns?created_from=2026-01-01T00:00:00")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_ARGUMENT"


async def test_未認証_Cookieがないとき401(anonymous: AsyncClient) -> None:
    response = await anonymous.get("/api/v1/campaigns")

    assert response.status_code == 401


async def test_詳細_Archive後も投稿と記憶と集計を返す(account: Account, clock: FixedClock) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    published = (await account.publish_post(session_id, post_body(campaign_id))).json()["data"]
    await complete_metrics(published["post_id"], x_pv_count=200, landing_user_count=50)
    await insert_memory(account.company_id, "この施策は反応が良い", campaign_ids=(campaign_id,))
    archived_at = clock.now()
    await archive_campaign(campaign_id, archived_at)

    response = await account.client.get(f"/api/v1/campaigns/{campaign_id}")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["campaign"]["id"] == campaign_id
    assert data["campaign"]["archived_at"] == archived_at.isoformat().replace("+00:00", "Z")
    assert data["posts"][0]["post_id"] == published["post_id"]
    assert data["posts"][0]["metrics"]["status"] == "completed"
    assert data["metrics_summary"]["landing_rate"] == 0.25
    assert data["metrics_summary"]["completed_count"] == 1
    assert data["memories"][0]["content"] == "この施策は反応が良い"
    assert data["has_more_posts"] is False


async def test_詳細_存在しないidのとき404_CAMPAIGN_NOT_FOUND(account: Account) -> None:
    response = await account.client.get("/api/v1/campaigns/999999999")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CAMPAIGN_NOT_FOUND"


async def test_詳細_idが0のとき400(account: Account) -> None:
    response = await account.client.get("/api/v1/campaigns/0")

    assert response.status_code == 400


async def test_編集_expected_updated_atが一致するとき200で更新されEmbeddingが更新される(
    account: Account, embedding: FakeEmbedding
) -> None:
    campaign_id = await account.create_campaign()
    detail = (await account.client.get(f"/api/v1/campaigns/{campaign_id}")).json()["data"]
    body = {
        **{k: detail["campaign"][k] for k in ("target_profile", "background", "objective", "plan")},
        "title": "編集後",
        "expected_updated_at": detail["campaign"]["updated_at"],
    }
    embedding.calls.clear()

    response = await account.client.put(f"/api/v1/campaigns/{campaign_id}", json=body)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == campaign_id
    assert data["title"] == "編集後"
    assert "agent_turn_id" not in data
    assert len(embedding.calls) == 1
    assert embedding.calls[0].startswith("施策タイトル: 編集後\n")


async def test_編集_検索対象の5項目が同じなら再Embeddingしない(
    account: Account, embedding: FakeEmbedding
) -> None:
    campaign_id = await account.create_campaign()
    detail = (await account.client.get(f"/api/v1/campaigns/{campaign_id}")).json()["data"]
    body = {
        **campaign_body(),
        "expected_updated_at": detail["campaign"]["updated_at"],
    }
    embedding.calls.clear()

    response = await account.client.put(f"/api/v1/campaigns/{campaign_id}", json=body)

    assert response.status_code == 200
    assert embedding.calls == []


async def test_編集の競合_古いexpected_updated_atのとき409_CAMPAIGN_CONFLICT(
    account: Account,
) -> None:
    campaign_id = await account.create_campaign()
    body = {**campaign_body(), "expected_updated_at": "2000-01-01T00:00:00Z"}

    response = await account.client.put(f"/api/v1/campaigns/{campaign_id}", json=body)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CAMPAIGN_CONFLICT"
    assert response.json()["error"]["agent_turn_id"] is None


async def test_編集_Archive済みCampaignはEmbeddingを生成せず409_CAMPAIGN_ARCHIVED(
    account: Account, embedding: FakeEmbedding, clock: FixedClock
) -> None:
    campaign_id = await account.create_campaign()
    detail = (await account.client.get(f"/api/v1/campaigns/{campaign_id}")).json()["data"]
    await archive_campaign(campaign_id, clock.now())
    embedding.calls.clear()

    response = await account.client.put(
        f"/api/v1/campaigns/{campaign_id}",
        json={
            **campaign_body(title="更新されない"),
            "expected_updated_at": detail["campaign"]["updated_at"],
        },
    )
    after = await account.client.get(f"/api/v1/campaigns/{campaign_id}")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CAMPAIGN_ARCHIVED"
    assert response.json()["error"]["retryable"] is False
    assert response.json()["error"]["agent_turn_id"] is None
    assert embedding.calls == []
    assert after.json()["data"]["campaign"]["title"] == campaign_body()["title"]


async def test_編集_他社の施策のとき404(account: Account, new_account: AccountFactory) -> None:
    other = await new_account()
    other_id = await other.create_campaign()
    body = {**campaign_body(), "expected_updated_at": "2030-01-01T00:00:00Z"}

    response = await account.client.put(f"/api/v1/campaigns/{other_id}", json=body)

    assert response.status_code == 404


async def test_編集_expected_updated_atがないとき400(account: Account) -> None:
    campaign_id = await account.create_campaign()

    response = await account.client.put(f"/api/v1/campaigns/{campaign_id}", json=campaign_body())

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_ARGUMENT"
    assert response.json()["error"]["field_errors"][0]["field"] == "expected_updated_at"


async def test_編集_業務条件違反のとき422_INVALID_CAMPAIGN(account: Account) -> None:
    campaign_id = await account.create_campaign()
    detail = (await account.client.get(f"/api/v1/campaigns/{campaign_id}")).json()["data"]
    body = {
        **campaign_body(title="a\nb"),
        "expected_updated_at": detail["campaign"]["updated_at"],
    }

    response = await account.client.put(f"/api/v1/campaigns/{campaign_id}", json=body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_CAMPAIGN"
    assert response.json()["error"]["field_errors"][0]["field"] == "title"


async def test_編集_CSRFトークンがないとき403(account: Account) -> None:
    campaign_id = await account.create_campaign()
    account.client.headers.pop("X-CSRF-Token")

    response = await account.client.put(
        f"/api/v1/campaigns/{campaign_id}",
        json={**campaign_body(), "expected_updated_at": "2030-01-01T00:00:00Z"},
    )

    assert response.status_code == 403


async def test_一覧の期間指定_created_toより前の施策だけを返す(
    account: Account, clock: FixedClock
) -> None:
    session_id = await account.create_session()
    old = await account.create_campaign(session_id, title="古い")
    clock.advance(30)
    boundary = clock.now().isoformat().replace("+00:00", "Z")
    clock.advance(3600)
    await account.create_campaign(session_id, title="新しい")

    before = await account.client.get(f"/api/v1/campaigns?created_to={quote(boundary)}")
    after = await account.client.get(f"/api/v1/campaigns?created_from={quote(boundary)}")

    assert [c["id"] for c in before.json()["data"]["campaigns"]] == [old]
    assert [c["title"] for c in after.json()["data"]["campaigns"]] == ["新しい"]
