import asyncio

from sqlalchemy import delete, select, update

from domain.campaign_rules import CampaignContent
from domain.search_text import build_campaign_search_text, content_hash
from models import CampaignEmbedding
from repositories.database import SessionLocal
from services.campaign_embedding_backfill import CampaignEmbeddingBackfillService
from services.context import ServiceContext
from tests.support.client import Account, campaign_body
from tests.support.fakes import FakeEmbedding


def _content(**overrides: str) -> CampaignContent:
    body = campaign_body(**overrides)
    return CampaignContent(
        body["title"],
        body["target_profile"],
        body["background"],
        body["objective"],
        body["plan"],
    )


async def _stored_hash(campaign_id: int) -> str | None:
    async with SessionLocal() as session:
        return await session.scalar(
            select(CampaignEmbedding.content_hash).where(
                CampaignEmbedding.campaign_id == campaign_id
            )
        )


async def test_Backfill_旧Projectionを現行の5項目Projectionへ更新し再実行ではスキップする(
    account: Account, ctx: ServiceContext, embedding: FakeEmbedding
) -> None:
    first_id = await account.create_campaign(title="1件目")
    second_id = await account.create_campaign(title="2件目")
    async with SessionLocal() as session, session.begin():
        await session.execute(
            update(CampaignEmbedding)
            .where(CampaignEmbedding.campaign_id.in_([first_id, second_id]))
            .values(content_hash="0" * 64)
        )
    embedding.calls.clear()

    first = await CampaignEmbeddingBackfillService(ctx).run(
        batch_size=1, company_id=account.company_id
    )

    first_text = build_campaign_search_text(_content(title="1件目"))
    second_text = build_campaign_search_text(_content(title="2件目"))
    assert first.scanned == first.updated == 2
    assert first.unchanged == first.conflicted == first.failed == 0
    assert first.last_id == second_id
    assert embedding.calls == [first_text, second_text]
    assert await _stored_hash(first_id) == content_hash(first_text)
    assert await _stored_hash(second_id) == content_hash(second_text)

    embedding.calls.clear()
    second = await CampaignEmbeddingBackfillService(ctx).run(company_id=account.company_id)

    assert second.scanned == second.unchanged == 2
    assert second.updated == 0
    assert embedding.calls == []


async def test_Backfill_失敗時は対象を飛ばさず最後に完了したIDから再開できる(
    account: Account, ctx: ServiceContext, embedding: FakeEmbedding
) -> None:
    first_id = await account.create_campaign(title="失敗対象")
    second_id = await account.create_campaign(title="後続対象")
    async with SessionLocal() as session, session.begin():
        await session.execute(
            update(CampaignEmbedding)
            .where(CampaignEmbedding.campaign_id.in_([first_id, second_id]))
            .values(content_hash="0" * 64)
        )
    embedding.fail = True

    failed = await CampaignEmbeddingBackfillService(ctx).run(company_id=account.company_id)

    assert failed.scanned == failed.failed == 1
    assert failed.updated == 0
    assert failed.last_id == 0

    embedding.fail = False
    recovered = await CampaignEmbeddingBackfillService(ctx).run(
        after_id=failed.last_id, company_id=account.company_id
    )

    assert recovered.scanned == recovered.updated == 2
    assert recovered.failed == 0
    assert recovered.last_id == second_id


async def test_Backfill_Embedding欠落時は新規作成する(
    account: Account, ctx: ServiceContext, embedding: FakeEmbedding
) -> None:
    campaign_id = await account.create_campaign()
    async with SessionLocal() as session, session.begin():
        await session.execute(
            delete(CampaignEmbedding).where(CampaignEmbedding.campaign_id == campaign_id)
        )
    embedding.calls.clear()

    result = await CampaignEmbeddingBackfillService(ctx).run(company_id=account.company_id)

    assert result.updated == 1
    assert embedding.calls == [build_campaign_search_text(_content())]
    assert await _stored_hash(campaign_id) == content_hash(build_campaign_search_text(_content()))


async def test_Backfill_生成中にタイトルが更新されたら古いEmbeddingで上書きしない(
    account: Account, ctx: ServiceContext, embedding: FakeEmbedding
) -> None:
    campaign_id = await account.create_campaign()
    detail = (await account.client.get(f"/api/v1/campaigns/{campaign_id}")).json()["data"]
    async with SessionLocal() as session, session.begin():
        await session.execute(
            update(CampaignEmbedding)
            .where(CampaignEmbedding.campaign_id == campaign_id)
            .values(content_hash="0" * 64)
        )
    gate = asyncio.Event()
    embedding.block_next = gate
    running = asyncio.create_task(
        CampaignEmbeddingBackfillService(ctx).run(company_id=account.company_id)
    )
    await asyncio.wait_for(embedding.blocked.wait(), 5)

    body = {
        **campaign_body(title="Backfill中に更新したタイトル"),
        "expected_updated_at": detail["campaign"]["updated_at"],
    }
    edited = await account.client.put(f"/api/v1/campaigns/{campaign_id}", json=body)
    gate.set()
    result = await running

    expected_hash = content_hash(
        build_campaign_search_text(_content(title="Backfill中に更新したタイトル"))
    )
    assert edited.status_code == 200
    assert result.conflicted == 1
    assert result.updated == 0
    assert await _stored_hash(campaign_id) == expected_hash
