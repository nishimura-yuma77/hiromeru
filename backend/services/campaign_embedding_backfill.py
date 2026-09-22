"""既存施策の検索Embeddingを現行Projectionへ更新する。"""

from dataclasses import dataclass
from typing import Literal

from clients.errors import EmbeddingError
from core.logging import get_logger, safe_error_text
from domain.campaign_rules import CampaignContent
from domain.search_text import build_campaign_search_text, content_hash
from repositories.campaigns import CampaignEmbeddingCandidate, CampaignRepository
from services.context import ServiceContext

_log = get_logger(__name__)


@dataclass(frozen=True)
class CampaignEmbeddingBackfillResult:
    """Backfillの処理件数と再開位置。"""

    scanned: int
    updated: int
    unchanged: int
    conflicted: int
    failed: int
    last_id: int


class CampaignEmbeddingBackfillService:
    """CampaignをID順に走査し、古い検索Embeddingだけを更新する。"""

    def __init__(self, ctx: ServiceContext) -> None:
        """外部Client、DB、時刻を受け取る。"""
        self._ctx = ctx

    async def run(
        self,
        *,
        batch_size: int = 100,
        after_id: int = 0,
        max_items: int | None = None,
        company_id: int | None = None,
    ) -> CampaignEmbeddingBackfillResult:
        """対象をページングし、内容が変わっていない場合だけEmbeddingを保存する。"""
        if batch_size <= 0 or after_id < 0 or (max_items is not None and max_items <= 0):
            raise ValueError("Backfillの件数とIDは正の値で指定してください。")

        scanned = updated = unchanged = conflicted = failed = 0
        last_id = after_id
        stopped = False
        while max_items is None or scanned < max_items:
            limit = batch_size
            if max_items is not None:
                limit = min(limit, max_items - scanned)
            async with self._ctx.session_factory() as session:
                candidates = await CampaignRepository(session).list_embedding_candidates(
                    after_id=last_id, limit=limit, company_id=company_id
                )
            if not candidates:
                break

            for candidate in candidates:
                scanned += 1
                search_text = build_campaign_search_text(candidate.content)
                digest = content_hash(search_text)
                if candidate.content_hash == digest:
                    unchanged += 1
                    last_id = candidate.campaign_id
                    continue
                try:
                    vector = await self._ctx.embedding.embed(search_text)
                except EmbeddingError as error:
                    failed += 1
                    _log.warning(
                        "campaign_embedding_backfill_failed",
                        campaign_id=candidate.campaign_id,
                        error=safe_error_text(error),
                    )
                    stopped = True
                    break
                result = await self._save_if_current(candidate, digest, vector)
                if result == "updated":
                    updated += 1
                elif result == "unchanged":
                    unchanged += 1
                else:
                    conflicted += 1
                    stopped = True
                    break
                last_id = candidate.campaign_id
            if stopped:
                break

        return CampaignEmbeddingBackfillResult(
            scanned, updated, unchanged, conflicted, failed, last_id
        )

    async def _save_if_current(
        self, candidate: CampaignEmbeddingCandidate, digest: str, vector: list[float]
    ) -> Literal["updated", "unchanged", "conflicted"]:
        """生成中に施策が変わっていなければ短いTransactionで保存する。"""
        async with self._ctx.session_factory() as session, session.begin():
            repository = CampaignRepository(session)
            current = await repository.get(candidate.company_id, candidate.campaign_id, lock=True)
            if current is None:
                return "conflicted"
            current_text = build_campaign_search_text(
                CampaignContent(
                    current.title,
                    current.target_profile,
                    current.background,
                    current.objective,
                    current.plan,
                )
            )
            if content_hash(current_text) != digest:
                return "conflicted"
            if await repository.get_embedding_hash(candidate.campaign_id) == digest:
                return "unchanged"
            await repository.upsert_embedding(
                candidate.campaign_id, vector, digest, self._ctx.clock.now()
            )
        return "updated"
