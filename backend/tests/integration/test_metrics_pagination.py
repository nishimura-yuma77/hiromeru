import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from core.config import Settings
from domain.enums import PostMetricStatus
from models import ApiListSnapshot, ApiListSnapshotItem, Campaign, PostMetric
from repositories.database import SessionLocal
from services.snapshot_paging import issue_snapshot_cursor, read_snapshot_cursor
from tests.conftest import AccountFactory
from tests.support.client import Account, post_body
from tests.support.db import complete_metrics
from tests.support.fakes import FixedClock


async def _campaign_with_post(
    account: Account,
    clock: FixedClock,
    title: str,
    *,
    x_pv_count: int | None = None,
    landing_user_count: int = 0,
) -> tuple[int, int]:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id, title=title)
    clock.advance(60)
    response = await account.publish_post(session_id, post_body(campaign_id, body=f"{title}の投稿"))
    assert response.status_code == 201, response.text
    post_id = int(response.json()["data"]["post_id"])
    if x_pv_count is not None:
        await complete_metrics(
            post_id,
            x_pv_count=x_pv_count,
            landing_user_count=landing_user_count,
        )
    return campaign_id, post_id


@pytest.mark.parametrize(
    ("limit", "expected_status"),
    [(0, 400), (1, 200), (50, 200), (51, 400)],
)
async def test_limit境界を検証する(account: Account, limit: int, expected_status: int) -> None:
    response = await account.client.get("/api/v1/metrics", params={"limit": limit})

    assert response.status_code == expected_status
    if expected_status == 400:
        assert response.json()["error"]["code"] == "INVALID_ARGUMENT"
    else:
        assert "next_cursor" in response.json()["data"]


async def test_campaignをPV降順とID降順で複数Page取得する(
    account: Account, clock: FixedClock
) -> None:
    low, _ = await _campaign_with_post(account, clock, "低PV", x_pv_count=10)
    tied_first, _ = await _campaign_with_post(account, clock, "同率1", x_pv_count=20)
    tied_second, _ = await _campaign_with_post(account, clock, "同率2", x_pv_count=20)

    first = (await account.client.get("/api/v1/metrics", params={"limit": 1})).json()["data"]
    second = (
        await account.client.get(
            "/api/v1/metrics", params={"limit": 1, "cursor": first["next_cursor"]}
        )
    ).json()["data"]
    third = (
        await account.client.get(
            "/api/v1/metrics", params={"limit": 1, "cursor": second["next_cursor"]}
        )
    ).json()["data"]

    assert [
        first["campaigns"][0]["id"],
        second["campaigns"][0]["id"],
        third["campaigns"][0]["id"],
    ] == [tied_second, tied_first, low]
    assert first["summary"] == second["summary"] == third["summary"]
    assert first["summary"]["post_count"] == 3
    assert third["next_cursor"] is None


async def test_Page間でMetricsとCampaignを更新してもsummaryとprojectionが固定される(
    account: Account, clock: FixedClock
) -> None:
    high, high_post = await _campaign_with_post(account, clock, "高PV", x_pv_count=300)
    middle, middle_post = await _campaign_with_post(account, clock, "中PV", x_pv_count=200)
    low, low_post = await _campaign_with_post(account, clock, "低PV", x_pv_count=100)
    first = (await account.client.get("/api/v1/metrics", params={"limit": 1})).json()["data"]

    archived_at = clock.now()
    async with SessionLocal() as session, session.begin():
        await session.execute(
            update(PostMetric)
            .where(PostMetric.post_id.in_([high_post, middle_post, low_post]))
            .values(x_pv_count=9999, landing_user_count=999)
        )
        await session.execute(
            update(Campaign)
            .where(Campaign.id == middle)
            .values(title="更新後", archived_at=archived_at)
        )

    second = (
        await account.client.get(
            "/api/v1/metrics", params={"limit": 1, "cursor": first["next_cursor"]}
        )
    ).json()["data"]
    third = (
        await account.client.get(
            "/api/v1/metrics", params={"limit": 1, "cursor": second["next_cursor"]}
        )
    ).json()["data"]

    assert [
        first["campaigns"][0]["id"],
        second["campaigns"][0]["id"],
        third["campaigns"][0]["id"],
    ] == [high, middle, low]
    assert first["summary"] == second["summary"] == third["summary"]
    assert third["summary"]["x_pv_count"] == 600
    assert second["campaigns"][0]["title"] == "中PV"
    assert second["campaigns"][0]["archived_at"] is None
    assert second["campaigns"][0]["x_pv_count"] == 200


async def test_期間をUTCへ正規化し異なる期間のcursorを拒否する(
    account: Account, clock: FixedClock
) -> None:
    await _campaign_with_post(account, clock, "期間内1")
    await _campaign_with_post(account, clock, "期間内2")
    params = {
        "published_from": "2000-01-01T09:00:00+09:00",
        "published_to": "2100-01-01T09:00:00+09:00",
        "limit": 1,
    }
    first = (await account.client.get("/api/v1/metrics", params=params)).json()["data"]

    mismatch = await account.client.get(
        "/api/v1/metrics",
        params={**params, "published_to": "2099-01-01T00:00:00Z", "cursor": first["next_cursor"]},
    )
    equivalent = await account.client.get(
        "/api/v1/metrics",
        params={
            "published_from": "2000-01-01T00:00:00Z",
            "published_to": "2100-01-01T00:00:00Z",
            "limit": 1,
            "cursor": first["next_cursor"],
        },
    )

    assert first["published_from"] == "2000-01-01T00:00:00Z"
    assert first["published_to"] == "2100-01-01T00:00:00Z"
    assert mismatch.status_code == 400
    assert mismatch.json()["error"]["code"] == "INVALID_ARGUMENT"
    assert equivalent.status_code == 200


async def test_cursorの別所有者_resource_期限_改ざんを拒否する(
    account: Account,
    new_account: AccountFactory,
    clock: FixedClock,
    settings: Settings,
) -> None:
    await _campaign_with_post(account, clock, "1件目")
    await _campaign_with_post(account, clock, "2件目")
    first = (await account.client.get("/api/v1/metrics", params={"limit": 1})).json()["data"]
    cursor = first["next_cursor"]
    parsed = read_snapshot_cursor(settings.auth_secret(), "metrics", cursor)
    wrong_resource = issue_snapshot_cursor(
        settings.auth_secret(),
        "posts",
        parsed.snapshot_id,
        parsed.position,
        parsed.filter_hash,
    )
    invalid_position = issue_snapshot_cursor(
        settings.auth_secret(),
        "metrics",
        parsed.snapshot_id,
        0,
        parsed.filter_hash,
    )
    out_of_range = issue_snapshot_cursor(
        settings.auth_secret(),
        "metrics",
        parsed.snapshot_id,
        parsed.position + 999,
        parsed.filter_hash,
    )
    other = await new_account()

    cross_owner = await other.client.get("/api/v1/metrics", params={"cursor": cursor})
    resource = await account.client.get("/api/v1/metrics", params={"cursor": wrong_resource})
    invalid = await account.client.get("/api/v1/metrics", params={"cursor": invalid_position})
    out_of_bounds = await account.client.get("/api/v1/metrics", params={"cursor": out_of_range})
    replacement = "A" if cursor[-1] != "A" else "B"
    tampered = await account.client.get(
        "/api/v1/metrics", params={"cursor": cursor[:-1] + replacement}
    )
    clock.advance(30 * 60)
    expired = await account.client.get("/api/v1/metrics", params={"cursor": cursor})

    for response in (cross_owner, resource, invalid, out_of_bounds, tampered, expired):
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_ARGUMENT"


async def test_空期間はzero_summaryと空campaignsを返す(account: Account) -> None:
    response = await account.client.get(
        "/api/v1/metrics",
        params={
            "published_from": "2099-01-01T09:00:00+09:00",
            "published_to": "2100-01-01T09:00:00+09:00",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["published_from"] == "2099-01-01T00:00:00Z"
    assert data["published_to"] == "2100-01-01T00:00:00Z"
    assert data["summary"] == {
        "post_count": 0,
        "completed_count": 0,
        "pending_count": 0,
        "failed_count": 0,
        "x_pv_count": 0,
        "landing_user_count": 0,
        "landing_rate": None,
    }
    assert data["campaigns"] == []
    assert data["next_cursor"] is None


async def test_状態混在summaryはcompletedだけのMetrics値を集計する(
    account: Account, clock: FixedClock
) -> None:
    campaign_id, _ = await _campaign_with_post(
        account, clock, "状態混在", x_pv_count=100, landing_user_count=25
    )
    session_id = await account.create_session()
    post_ids: dict[str, int] = {}
    for name in ("pending", "failed"):
        clock.advance(60)
        response = await account.publish_post(
            session_id,
            post_body(campaign_id, body=name),
        )
        assert response.status_code == 201, response.text
        post_ids[name] = int(response.json()["data"]["post_id"])
    async with SessionLocal() as session, session.begin():
        await session.execute(
            update(PostMetric)
            .where(PostMetric.post_id == post_ids["failed"])
            .values(
                status=PostMetricStatus.FAILED,
                x_pv_count=999,
                landing_user_count=999,
                measured_at=clock.now(),
            )
        )

    data = (await account.client.get("/api/v1/metrics")).json()["data"]

    assert data["summary"] == {
        "post_count": 3,
        "completed_count": 1,
        "pending_count": 1,
        "failed_count": 1,
        "x_pv_count": 100,
        "landing_user_count": 25,
        "landing_rate": 0.25,
    }
    assert data["campaigns"][0]["archived_at"] is None


async def test_先頭Pageで期限切れSnapshotを100件まで削除する(
    account: Account, clock: FixedClock
) -> None:
    expired_ids = [uuid.uuid4() for _ in range(101)]
    async with SessionLocal() as session, session.begin():
        session.add_all(
            ApiListSnapshot(
                id=snapshot_id,
                marketer_id=account.marketer_id,
                resource="metrics",
                filter_hash="a" * 64,
                created_at=clock.now() - timedelta(hours=2),
                expires_at=clock.now() - timedelta(hours=1),
            )
            for snapshot_id in expired_ids
        )
        session.add_all(
            ApiListSnapshotItem(snapshot_id=snapshot_id, position=0, item={"id": index})
            for index, snapshot_id in enumerate(expired_ids)
        )

    response = await account.client.get("/api/v1/metrics")

    async with SessionLocal() as session:
        snapshot_count = await session.scalar(
            select(func.count())
            .select_from(ApiListSnapshot)
            .where(ApiListSnapshot.id.in_(expired_ids))
        )
        item_count = await session.scalar(
            select(func.count())
            .select_from(ApiListSnapshotItem)
            .where(ApiListSnapshotItem.snapshot_id.in_(expired_ids))
        )
    assert response.status_code == 200
    assert snapshot_count == 1
    assert item_count == 1
