"""完了Metricsから決定論的な評価記憶を生成するCron worker。"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from clients.errors import EmbeddingError
from core.logging import get_logger
from domain.evaluation_memory import build_evaluation_memory_content
from repositories.memory_cron import (
    EvaluationMemoryClaim,
    MemoryCronRepository,
    MemoryTransition,
)
from services.context import ServiceContext

_log = get_logger(__name__)


@dataclass(frozen=True)
class EvaluationMemoryRunResult:
    """1回のworker起動で処理した件数。"""

    claimed: int = 0
    created: int = 0
    failed: int = 0


class EvaluationMemoryService:
    """Metricsとは別TokenでClaimし、Embedding後に記憶を原子的に保存する。"""

    def __init__(self, ctx: ServiceContext) -> None:
        """EmbeddingとDBを含む実行Contextを受け取る。"""
        self._ctx = ctx

    async def run(
        self,
        *,
        max_items: int | None = None,
        should_continue_claiming: Callable[[], bool] = lambda: True,
    ) -> EvaluationMemoryRunResult:
        """Invocation上限までBatch単位で評価記憶を生成する。"""
        configured = self._ctx.settings.cron_memory_max_items
        limit = configured if max_items is None else max(0, min(configured, max_items))
        claimed = created = failed = 0
        await self._terminalize_interrupted()
        while claimed < limit and should_continue_claiming():
            batch_limit = min(self._ctx.settings.cron_memory_batch_size, limit - claimed)
            claims = await self._claim(batch_limit)
            if not claims:
                break
            claimed += len(claims)
            results = await asyncio.gather(*(self._process(claim) for claim in claims))
            created += results.count(MemoryTransition.CREATED)
            failed += results.count(MemoryTransition.FAILED)
        return EvaluationMemoryRunResult(claimed, created, failed)

    async def _terminalize_interrupted(self) -> None:
        now = self._ctx.clock.now()
        async with self._ctx.session_factory() as session, session.begin():
            await MemoryCronRepository(session).terminalize_interrupted(
                now, self._ctx.settings.cron_memory_max_attempts
            )

    async def _claim(self, limit: int) -> list[EvaluationMemoryClaim]:
        now = self._ctx.clock.now()
        async with self._ctx.session_factory() as session, session.begin():
            return await MemoryCronRepository(session).claim(
                now=now,
                lease_expires_at=now + timedelta(seconds=self._ctx.settings.lease_seconds),
                max_attempts=self._ctx.settings.cron_memory_max_attempts,
                limit=limit,
                new_uuid=self._ctx.new_uuid,
            )

    async def _process(self, claim: EvaluationMemoryClaim) -> MemoryTransition:
        content = build_evaluation_memory_content(
            claim.campaign_title,
            claim.post_body,
            claim.x_pv_count,
            claim.landing_user_count,
        )
        try:
            embedding = await self._ctx.embedding.embed(content)
        except EmbeddingError:
            return await self._record_failure(claim, "EMBEDDING_FAILED")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - 詳細を保存せず固定Codeへ変換する
            return await self._record_failure(claim, "MEMORY_UNEXPECTED")
        try:
            now = self._ctx.clock.now()
            async with self._ctx.session_factory() as session, session.begin():
                result, _ = await MemoryCronRepository(session).save_created(
                    claim, content=content, embedding=embedding, now=now
                )
                return result
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - rollback後の別Transactionで固定Codeだけを保存する
            return await self._record_failure(claim, "MEMORY_SAVE_FAILED")

    async def _record_failure(
        self, claim: EvaluationMemoryClaim, code: str
    ) -> MemoryTransition:
        _log.warning(
            "evaluation_memory_failed",
            post_id=claim.post_id,
            error_code=code,
            attempt_count=claim.attempt_count,
        )
        now = self._ctx.clock.now()
        async with self._ctx.session_factory() as session, session.begin():
            return await MemoryCronRepository(session).finish_failure(
                claim.post_id,
                claim.token,
                now=now,
                error_code=code,
                max_attempts=self._ctx.settings.cron_memory_max_attempts,
            )
