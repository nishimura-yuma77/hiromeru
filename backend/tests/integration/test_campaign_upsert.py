import asyncio
import uuid

from sqlalchemy import func, select

from models import AgentTurn, Campaign
from repositories.database import SessionLocal
from tests.conftest import AccountFactory
from tests.support.client import Account, campaign_body
from tests.support.fakes import FakeEmbedding, FixedClock


async def test_新規作成_idなしのとき201でidとagent_turn_idを返す(account: Account) -> None:
    session_id = await account.create_session()

    response = await account.upsert_campaign(session_id, campaign_body())

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["id"] > 0
    assert data["title"] == "春の新規フォロワー獲得"
    assert data["agent_turn_id"] > 0
    assert data["created_at"].endswith("Z")


async def test_上書き_expected_updated_atが一致するとき200で内容が更新される(
    account: Account,
) -> None:
    session_id = await account.create_session()
    created = (await account.upsert_campaign(session_id, campaign_body())).json()["data"]

    response = await account.upsert_campaign(
        session_id,
        campaign_body(
            id=created["id"], expected_updated_at=created["created_at"], title="更新後タイトル"
        ),
    )

    assert response.status_code == 200
    assert response.json()["data"]["title"] == "更新後タイトル"
    detail = await account.client.get(f"/api/v1/campaigns/{created['id']}")
    assert detail.json()["data"]["campaign"]["title"] == "更新後タイトル"


async def test_上書きの競合_expected_updated_atが古いとき409_CAMPAIGN_CONFLICT(
    account: Account, clock: object
) -> None:
    del clock
    session_id = await account.create_session()
    created = (await account.upsert_campaign(session_id, campaign_body())).json()["data"]

    response = await account.upsert_campaign(
        session_id,
        campaign_body(id=created["id"], expected_updated_at="2000-01-01T00:00:00Z"),
    )

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "CAMPAIGN_CONFLICT"
    assert error["agent_turn_id"] is not None


async def test_他社の施策の上書き_idが他社のとき404_CAMPAIGN_NOT_FOUND(
    account: Account, new_account: AccountFactory
) -> None:
    other = await new_account()
    other_id = await other.create_campaign()
    session_id = await account.create_session()

    response = await account.upsert_campaign(
        session_id, campaign_body(id=other_id, expected_updated_at="2030-01-01T00:00:00Z")
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CAMPAIGN_NOT_FOUND"


async def test_Body検証_expected_updated_atがidなしで指定されたとき400_INVALID_ARGUMENT(
    account: Account,
) -> None:
    session_id = await account.create_session()

    response = await account.upsert_campaign(
        session_id, campaign_body(expected_updated_at="2030-01-01T00:00:00Z")
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_ARGUMENT"
    assert response.json()["error"]["agent_turn_id"] is not None


async def test_業務条件違反_タイトルに改行があるとき422_INVALID_CAMPAIGN(
    account: Account,
) -> None:
    session_id = await account.create_session()

    response = await account.upsert_campaign(session_id, campaign_body(title="a\nb"))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_CAMPAIGN"


async def test_Embedding失敗_生成できないとき500_EMBEDDING_FAILEDで施策を保存しない(
    account: Account, embedding: FakeEmbedding
) -> None:
    session_id = await account.create_session()
    embedding.fail = True
    title = f"保存されない施策-{uuid.uuid4().hex}"

    response = await account.upsert_campaign(session_id, campaign_body(title=title))

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "EMBEDDING_FAILED"
    assert response.json()["error"]["retryable"] is True
    async with SessionLocal() as session:
        count = await session.scalar(
            select(func.count()).select_from(Campaign).where(Campaign.title == title)
        )
    assert count == 0


async def test_冪等性_同じキーと同じBodyの再送のとき同じ応答を返し施策は増えない(
    account: Account,
) -> None:
    session_id = await account.create_session()
    key = str(uuid.uuid4())
    first = await account.upsert_campaign(session_id, campaign_body(), key)

    second = await account.upsert_campaign(session_id, campaign_body(), key)

    assert second.status_code == first.status_code == 201
    assert second.json() == first.json()
    async with SessionLocal() as session:
        turns = await session.scalar(
            select(func.count()).select_from(AgentTurn).where(AgentTurn.session_id == session_id)
        )
    assert turns == 1


async def test_キー再利用_同じキーで別のBodyのとき409_IDEMPOTENCY_KEY_REUSED(
    account: Account,
) -> None:
    session_id = await account.create_session()
    key = str(uuid.uuid4())
    await account.upsert_campaign(session_id, campaign_body(), key)

    response = await account.upsert_campaign(session_id, campaign_body(title="別"), key)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


async def test_キー検証_Idempotency_KeyがUUIDでないとき400(account: Account) -> None:
    session_id = await account.create_session()

    response = await account.upsert_campaign(session_id, campaign_body(), "not-a-uuid")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_IDEMPOTENCY_KEY"


async def test_Session所有権_他人のSessionのとき404で施策を作らない(
    account: Account, new_account: AccountFactory
) -> None:
    other = await new_account()
    other_session = await other.create_session()

    response = await account.upsert_campaign(other_session, campaign_body())

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "AGENT_SESSION_NOT_FOUND"


async def test_Bodyがマスクされる_履歴のAPI実行Turnにメールアドレスの生値が残らない(
    account: Account,
) -> None:
    session_id = await account.create_session()
    await account.upsert_campaign(
        session_id, campaign_body(background="担当は taro@example.com です")
    )

    history = await account.client.get(f"/api/v1/agent-sessions/{session_id}")

    assert history.status_code == 200
    assert "taro@example.com" not in history.text


async def test_Lease失効後の再取得_処理が止まったRequestの実行権を同じキーの再送が奪い完了する(
    account: Account, embedding: FakeEmbedding, clock: FixedClock
) -> None:
    session_id = await account.create_session()
    key = str(uuid.uuid4())
    embedding.block_next = asyncio.Event()
    stalled = asyncio.create_task(account.upsert_campaign(session_id, campaign_body(), key))
    await asyncio.wait_for(embedding.blocked.wait(), 5)
    clock.advance(331)

    retried = await account.upsert_campaign(session_id, campaign_body(), key)
    embedding.blocked.clear()
    stalled.cancel()
    await asyncio.gather(stalled, return_exceptions=True)

    assert retried.status_code == 201
    replay = await account.upsert_campaign(session_id, campaign_body(), key)
    assert replay.json() == retried.json()
    async with SessionLocal() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(Campaign)
            .where(Campaign.id == retried.json()["data"]["id"])
        )
    assert count == 1
