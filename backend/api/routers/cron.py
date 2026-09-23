"""Vercel Cron専用Endpoint。Browser認証・CSRFとは独立して保護する。"""

import asyncio
import hmac
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from api.deps import Context
from api.middleware import REQUEST_DEADLINE_KEY
from services.evaluation_memory import EvaluationMemoryService
from services.metric_collection import MetricCollectionService

router = APIRouter(prefix="/api/cron", tags=["cron"])
_RESERVED_FINISH_SECONDS = 60.0


@dataclass(frozen=True)
class ClaimBudget:
    """新しいBatchをClaimできる単調時刻の期限。"""

    claim_deadline: float
    now: Callable[[], float]

    def available(self) -> bool:
        """期限と等しい場合は新しいClaimを開始しない。"""
        return self.now() < self.claim_deadline


def _authorized(request: Request, ctx: Context) -> bool:
    secret = ctx.settings.cron_secret.get_secret_value()
    if not secret.strip() or ctx.settings.vercel_env == "preview":
        return False
    expected = f"Bearer {secret}".encode()
    supplied = request.headers.get("authorization", "").encode()
    return hmac.compare_digest(supplied, expected)


@router.get("/post-metrics")
async def collect_post_metrics(request: Request, ctx: Context) -> Response:
    """Metrics収集と評価記憶生成を、共有時間Budget内で順に実行する。"""
    if not _authorized(request, ctx):
        return Response(status_code=401, headers={"Cache-Control": "no-store"})
    loop = asyncio.get_running_loop()
    request_deadline = request.scope.get(REQUEST_DEADLINE_KEY)
    claim_deadline = (
        float(request_deadline) - _RESERVED_FINISH_SECONDS
        if request_deadline is not None
        else loop.time()
    )
    budget = ClaimBudget(claim_deadline, loop.time)
    metrics = await MetricCollectionService(ctx).run(
        should_continue_claiming=budget.available
    )
    memories = await EvaluationMemoryService(ctx).run(
        should_continue_claiming=budget.available
    )
    return JSONResponse(
        {
            "status": "ok",
            "metrics_claimed": metrics.claimed,
            "metrics_completed": metrics.completed,
            "metrics_failed": metrics.failed,
            "metrics_deferred": metrics.deferred,
            "memories_claimed": memories.claimed,
            "memories_created": memories.created,
            "memories_failed": memories.failed,
        },
        headers={"Cache-Control": "no-store"},
    )
