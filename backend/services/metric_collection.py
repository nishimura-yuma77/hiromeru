"""X/GA4初週MetricsをLease付きで収集するCron worker。"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

from clients.errors import (
    Ga4ConfigurationError,
    Ga4ProviderError,
    Ga4RetryableProviderError,
    XApiConfigurationError,
    XApiProviderError,
    XApiRetryableProviderError,
)
from clients.ga4 import Ga4ReportQuery
from core.logging import get_logger
from repositories.metric_cron import MetricClaim, MetricCronRepository, MetricTransition
from services.context import ServiceContext

_log = get_logger(__name__)


@dataclass(frozen=True)
class MetricRunResult:
    """1回のworker起動で処理した件数。"""

    claimed: int = 0
    completed: int = 0
    failed: int = 0
    deferred: int = 0


class _ItemResult(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    DEFERRED = "deferred"
    LEASE_LOST = "lease_lost"


@dataclass(frozen=True)
class _ProviderFailure:
    provider: str
    code: str
    retryable: bool


class MetricCollectionService:
    """Claimを分割し、DB Lock外でProviderを呼び出す。"""

    def __init__(self, ctx: ServiceContext) -> None:
        """ProviderとDBを含む実行Contextを受け取る。"""
        self._ctx = ctx

    async def run(
        self,
        *,
        max_items: int | None = None,
        should_continue_claiming: Callable[[], bool] = lambda: True,
    ) -> MetricRunResult:
        """Invocation上限までBatch単位でClaimして処理する。"""
        configured = self._ctx.settings.cron_metric_max_items
        limit = configured if max_items is None else max(0, min(configured, max_items))
        counts = {"claimed": 0, "completed": 0, "failed": 0, "deferred": 0}
        await self._terminalize_interrupted()
        while counts["claimed"] < limit and should_continue_claiming():
            batch_limit = min(
                self._ctx.settings.cron_metric_batch_size, limit - counts["claimed"]
            )
            claims = await self._claim(batch_limit)
            if not claims:
                break
            counts["claimed"] += len(claims)
            outcomes = await asyncio.gather(*(self._process(claim) for claim in claims))
            for outcome in outcomes:
                if outcome in (_ItemResult.COMPLETED, _ItemResult.FAILED, _ItemResult.DEFERRED):
                    counts[outcome.value] += 1
        return MetricRunResult(**counts)

    async def _terminalize_interrupted(self) -> None:
        now = self._ctx.clock.now()
        async with self._ctx.session_factory() as session, session.begin():
            await MetricCronRepository(session).terminalize_interrupted(
                now, self._ctx.settings.cron_metric_max_attempts
            )

    async def _claim(self, limit: int) -> list[MetricClaim]:
        now = self._ctx.clock.now()
        lease_expires_at = now + timedelta(seconds=self._ctx.settings.lease_seconds)
        async with self._ctx.session_factory() as session, session.begin():
            return await MetricCronRepository(session).claim(
                now=now,
                lease_expires_at=lease_expires_at,
                max_attempts=self._ctx.settings.cron_metric_max_attempts,
                limit=limit,
                new_uuid=self._ctx.new_uuid,
            )

    async def _process(self, claim: MetricClaim) -> _ItemResult:
        ready = await self._complete_if_ready(claim)
        if ready == MetricTransition.COMPLETED:
            return _ItemResult.COMPLETED
        if ready == MetricTransition.LEASE_LOST:
            return _ItemResult.LEASE_LOST
        calls = []
        if claim.x_pv_count is None:
            calls.append(self._collect_x(claim))
        if claim.landing_user_count is None:
            calls.append(self._collect_ga4(claim))
        results = await asyncio.gather(*calls)
        if MetricTransition.LEASE_LOST in results:
            return _ItemResult.LEASE_LOST
        failures = [result for result in results if isinstance(result, _ProviderFailure)]
        if failures:
            selected = next((failure for failure in failures if not failure.retryable), failures[0])
            transition = await self._finish_failure(claim, selected)
            return _item_result(transition)
        if MetricTransition.COMPLETED in results:
            return _ItemResult.COMPLETED
        transition = await self._complete_if_ready(claim)
        return _item_result(transition)

    async def _collect_x(self, claim: MetricClaim) -> MetricTransition | _ProviderFailure:
        try:
            value = await self._ctx.x_api.get_impression_count(claim.x_post_id)
            return await self._save_success(claim, "x", value)
        except XApiRetryableProviderError:
            return self._failure(claim, "x", "X_PROVIDER_RETRYABLE", True)
        except XApiConfigurationError:
            return self._failure(claim, "x", "X_CONFIGURATION_ERROR", False)
        except XApiProviderError:
            return self._failure(claim, "x", "X_PROVIDER_ERROR", False)
        except Exception:  # noqa: BLE001 - 詳細を保存せず固定Codeへ変換する
            return self._failure(claim, "x", "METRIC_PROVIDER_UNEXPECTED", True)

    async def _collect_ga4(self, claim: MetricClaim) -> MetricTransition | _ProviderFailure:
        query = Ga4ReportQuery(
            published_at=claim.published_at,
            scheduled_at=claim.scheduled_at,
            utm_source=claim.utm_source,
            utm_medium=claim.utm_medium,
            utm_campaign=claim.utm_campaign,
            utm_content=claim.utm_content,
        )
        try:
            value = await self._ctx.ga4.get_active_users(query)
            return await self._save_success(claim, "ga4", value)
        except Ga4RetryableProviderError:
            return self._failure(claim, "ga4", "GA4_PROVIDER_RETRYABLE", True)
        except Ga4ConfigurationError:
            return self._failure(claim, "ga4", "GA4_CONFIGURATION_ERROR", False)
        except Ga4ProviderError:
            return self._failure(claim, "ga4", "GA4_PROVIDER_ERROR", False)
        except Exception:  # noqa: BLE001 - 詳細を保存せず固定Codeへ変換する
            return self._failure(claim, "ga4", "METRIC_PROVIDER_UNEXPECTED", True)

    def _failure(
        self, claim: MetricClaim, provider: str, code: str, retryable: bool
    ) -> _ProviderFailure:
        _log.warning(
            "metric_provider_failed",
            post_id=claim.post_id,
            provider=provider,
            error_code=code,
            attempt_count=claim.attempt_count,
        )
        return _ProviderFailure(provider, code, retryable)

    async def _save_success(
        self, claim: MetricClaim, provider: str, value: int
    ) -> MetricTransition:
        now = self._ctx.clock.now()
        async with self._ctx.session_factory() as session, session.begin():
            return await MetricCronRepository(session).save_provider_success(
                claim.post_id, claim.token, provider=provider, value=value, now=now
            )

    async def _complete_if_ready(self, claim: MetricClaim) -> MetricTransition:
        now = self._ctx.clock.now()
        async with self._ctx.session_factory() as session, session.begin():
            return await MetricCronRepository(session).complete_if_ready(
                claim.post_id, claim.token, now
            )

    async def _finish_failure(
        self, claim: MetricClaim, failure: _ProviderFailure
    ) -> MetricTransition:
        now = self._ctx.clock.now()
        async with self._ctx.session_factory() as session, session.begin():
            return await MetricCronRepository(session).finish_failure(
                claim.post_id,
                claim.token,
                now=now,
                error_code=failure.code,
                retryable=failure.retryable,
                max_attempts=self._ctx.settings.cron_metric_max_attempts,
            )


def _item_result(transition: MetricTransition) -> _ItemResult:
    if transition == MetricTransition.COMPLETED:
        return _ItemResult.COMPLETED
    if transition == MetricTransition.FAILED:
        return _ItemResult.FAILED
    if transition == MetricTransition.DEFERRED:
        return _ItemResult.DEFERRED
    return _ItemResult.LEASE_LOST
