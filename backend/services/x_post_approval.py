"""X投稿公開（承認API。API_DESIGN 3.1）。

X APIへの投稿は副作用があるため、結果が不明な場合に自動で再投稿しない。
X投稿の成功結果は、DB保存より先に `external_result` へ独立したTransactionで保存し、
その後のDB保存が失敗しても、同じキーの再送でDB保存だけを再実行できるようにする。
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any

from pydantic import BeforeValidator, StringConstraints, ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from clients.errors import (
    EmbeddingError,
    XApiConfigurationError,
    XApiOutcomeUnknownError,
    XApiRejectedError,
)
from core.errors import AppError, FieldError, LeaseLostError
from core.logging import get_logger, safe_error_text
from domain.constants import (
    DB_SAVE_BACKOFF_BASE_SECONDS,
    DB_SAVE_MAX_ATTEMPTS,
    MAX_LANDING_URL_LENGTH,
)
from domain.enums import ApiIdempotencyStatus, ApiOperation
from domain.requests import StrictModel, XPostRequest
from domain.search_text import build_post_search_text, content_hash
from domain.timefmt import format_utc, parse_aware_datetime
from domain.tracking import TrackingUrl, build_tracking_url, is_valid_landing_url
from domain.x_text import contains_url, is_within_x_limit
from repositories.campaigns import CampaignRepository
from repositories.idempotency import IdempotencyRepository
from repositories.posts import NewPost, PostRepository
from services.approval import (
    ApprovalExecutor,
    ApprovalOutcome,
    ApprovalStore,
    ExecutionContext,
    error_body,
    success_body,
)
from services.context import AuthContext, ServiceContext
from services.validation import BodyLoader, validate_model

_log = get_logger(__name__)


def _parse_published_at(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("published_at must be an ISO 8601 string")
    return parse_aware_datetime(value)


class ExternalResult(StrictModel):
    """DB-only再開に使う、永続化済みX成功結果。"""

    x_post_id: Annotated[str, StringConstraints(min_length=1, max_length=255)]
    text: Annotated[str, StringConstraints(min_length=1)]
    tracked_url: Annotated[str, StringConstraints(min_length=1, max_length=MAX_LANDING_URL_LENGTH)]
    published_at: Annotated[datetime, BeforeValidator(_parse_published_at)]


@dataclass(frozen=True)
class PublishedPost:
    """X投稿に成功した投稿の、保存する内容。"""

    body: str
    x_post_id: str
    published_at: datetime
    tracking: TrackingUrl


async def insert_published_post(
    session: AsyncSession,
    ctx: ExecutionContext,
    campaign_id: int,
    published: PublishedPost,
    embedding: list[float],
    *,
    response_turn_id: int,
) -> dict[str, Any]:
    """通常承認と運用復旧で共有するPost関連データの保存処理。"""
    tracking = published.tracking
    post = await PostRepository(session).insert_published(
        NewPost(
            company_id=ctx.auth.company_id,
            marketer_id=ctx.auth.marketer_id,
            campaign_id=campaign_id,
            api_idempotency_request_id=ctx.request_id,
            body=published.body,
            x_post_id=published.x_post_id,
            published_at=published.published_at,
            landing_url=tracking.landing_url,
            utm_source=tracking.utm_source,
            utm_medium=tracking.utm_medium,
            utm_campaign=tracking.utm_campaign,
            utm_content=tracking.utm_content,
            tracked_url=tracking.tracked_url,
            embedding=embedding,
            content_hash=content_hash(build_post_search_text(published.body)),
        )
    )
    return success_body(
        {
            "post_id": post.id,
            "agent_turn_id": response_turn_id,
            "campaign_id": campaign_id,
            "x_post_id": published.x_post_id,
            "body": published.body,
            "tracked_url": tracking.tracked_url,
            "published_at": format_utc(published.published_at),
        }
    )


def published_from_external_result(
    request: XPostRequest, key: str, external: dict[str, Any]
) -> PublishedPost:
    """保存済みX結果を再検証し、DB保存用の値へ変換する。

    Raises:
        ValueError: Schemaまたは元Requestとの対応が不正な場合。
    """
    try:
        stored = ExternalResult.model_validate(external)
    except ValidationError:
        raise ValueError("invalid external result schema") from None
    tracked_url = stored.tracked_url
    text = stored.text
    if not text.endswith(f"\n{tracked_url}"):
        raise ValueError("external text and tracked URL do not match")
    post_body = text.removesuffix(f"\n{tracked_url}")
    tracking = build_tracking_url(request.landing_url, request.campaign_id, key)
    if post_body != request.body or tracked_url != tracking.tracked_url:
        raise ValueError("external result does not match original request")
    return PublishedPost(
        post_body,
        stored.x_post_id,
        stored.published_at,
        TrackingUrl(
            request.landing_url,
            tracking.utm_source,
            tracking.utm_medium,
            tracking.utm_campaign,
            tracking.utm_content,
            tracked_url,
        ),
    )


class XPostApprovalService:
    """最終承認済みの投稿内容をXへ投稿し、成功後に投稿・UTM・計測予定を保存する。"""

    def __init__(self, ctx: ServiceContext) -> None:
        """サービスの依存を受け取る。"""
        self._ctx = ctx
        self._executor = ApprovalExecutor(ctx)

    async def publish(
        self, auth: AuthContext, session_id: int, body_loader: BodyLoader, key_header: str | None
    ) -> ApprovalOutcome:
        """投稿を公開する。

        Raises:
            AppError: 履歴へ保存しないエラー（親Session・Body・キー・処理中など）。
        """
        prepared = await self._executor.prepare(
            auth, session_id, ApiOperation.PUBLISH_X_POST, body_loader, key_header
        )
        if isinstance(prepared, ApprovalOutcome):
            return prepared
        try:
            return await self._run(prepared.execution, prepared.body)
        except LeaseLostError:
            return await self._executor.replay_after_lease_lost(prepared.execution)

    async def resume_persistence(
        self, ctx: ExecutionContext, body: dict[str, Any], external: dict[str, Any]
    ) -> ApprovalOutcome:
        """運用復旧から、Xを呼ばずに保存済み外部結果のDB保存だけを再開する。"""
        return await self._resume(ctx, body, external)

    async def _run(self, ctx: ExecutionContext, body: dict[str, Any]) -> ApprovalOutcome:
        if ctx.external_result is not None:
            return await self._resume(ctx, body, ctx.external_result)
        try:
            request = validate_model(XPostRequest, body)
            self._validate_fields(request)
            tracking = build_tracking_url(request.landing_url, request.campaign_id, str(ctx.key))
            self._validate_post_length(request, tracking)
            await self._require_campaign(ctx, request.campaign_id)
            embedding = await self._embed(request.body)
            # X API呼び出しの直前にも再確認し、Embedding生成中のArchive Raceを閉じる。
            await self._require_campaign(ctx, request.campaign_id)
        except AppError as error:
            return await self._fail(ctx, error, ApiIdempotencyStatus.FAILED)
        return await self._post_to_x(ctx, request, tracking, embedding)

    @staticmethod
    def _validate_fields(request: XPostRequest) -> None:
        """本文と遷移先URLを検証し、FieldごとのErrorをまとめて返す。"""
        field_errors: list[FieldError] = []
        if contains_url(request.body):
            field_errors.append(
                {
                    "field": "body",
                    "code": "INVALID_FORMAT",
                    "message": "投稿本文にURLを含めることはできません。",
                }
            )
        if not is_valid_landing_url(request.landing_url):
            field_errors.append(
                {
                    "field": "landing_url",
                    "code": "INVALID_URL",
                    "message": "遷移先URLが正しくありません。",
                }
            )
        if field_errors:
            raise AppError("INVALID_X_POST", field_errors=field_errors)

    @staticmethod
    def _validate_post_length(request: XPostRequest, tracking: TrackingUrl) -> None:
        """UTM追加後のURLと、Xへ送る最終本文の文字数を検証する。"""
        field_errors: list[FieldError] = []
        if len(tracking.tracked_url) > MAX_LANDING_URL_LENGTH:
            field_errors.append(
                {
                    "field": "landing_url",
                    "code": "TOO_LONG",
                    "message": "UTM追加後の遷移先URLは2,048文字以内にしてください。",
                }
            )
        if not is_within_x_limit(f"{request.body}\n{tracking.tracked_url}"):
            field_errors.append(
                {
                    "field": None,
                    "code": "X_LENGTH_EXCEEDED",
                    "message": "投稿本文と遷移先URLの合計がXの文字数上限を超えています。",
                }
            )
        if field_errors:
            raise AppError("INVALID_X_POST", field_errors=field_errors)

    async def _require_campaign(self, ctx: ExecutionContext, campaign_id: int) -> None:
        async with self._ctx.session_factory() as session:
            campaign = await CampaignRepository(session).get(ctx.auth.company_id, campaign_id)
            if campaign is None:
                raise AppError("CAMPAIGN_NOT_FOUND")
            if campaign.archived_at is not None:
                raise AppError("CAMPAIGN_ARCHIVED")

    async def _embed(self, body: str) -> list[float]:
        """URLを除去した本文からEmbeddingを生成する。失敗した場合はXへ投稿しない。"""
        try:
            return await self._ctx.embedding.embed(build_post_search_text(body))
        except EmbeddingError as error:
            _log.warning("post_embedding_failed", error=safe_error_text(error))
            raise AppError("EMBEDDING_FAILED") from None

    async def _post_to_x(
        self,
        ctx: ExecutionContext,
        request: XPostRequest,
        tracking: TrackingUrl,
        embedding: list[float],
    ) -> ApprovalOutcome:
        text = f"{request.body}\n{tracking.tracked_url}"
        async with self._ctx.session_factory() as session, session.begin():
            started = await IdempotencyRepository(session).mark_external_started(
                ctx.request_id, ctx.token, self._ctx.clock.now()
            )
            if not started:
                raise LeaseLostError
        external_saved = False
        try:
            try:
                result = await self._ctx.x_api.post(text)
            except (XApiConfigurationError, XApiRejectedError):
                failure = AppError("X_POST_FAILED", retryable=True)
                return await self._fail(ctx, failure, ApiIdempotencyStatus.FAILED)
            except XApiOutcomeUnknownError as error:
                _log.warning("x_post_outcome_unknown", error=safe_error_text(error))
                return await self._outcome_unknown(ctx)
            published_at = self._ctx.clock.now()
            external = {
                "x_post_id": result.x_post_id,
                "text": text,
                "tracked_url": tracking.tracked_url,
                "published_at": format_utc(published_at),
            }
            if not await self._save_external_result(ctx, external):
                return await self._outcome_unknown(ctx)
            external_saved = True
            published = PublishedPost(request.body, result.x_post_id, published_at, tracking)
            return await self._save_with_retry(ctx, request.campaign_id, published, embedding)
        except LeaseLostError:
            raise
        except Exception as error:  # noqa: BLE001 - 外部作用開始後は結果不明として安全側へ倒す
            _log.error("x_post_unexpected_error", error=safe_error_text(error))
            if external_saved:
                return await self._save_failed(ctx)
            return await self._outcome_unknown(ctx)

    async def _save_external_result(self, ctx: ExecutionContext, external: dict[str, Any]) -> bool:
        """X投稿の成功結果を、独立した短いTransactionで保存する。保存できなければ False。"""
        try:
            async with self._ctx.session_factory() as session, session.begin():
                return await IdempotencyRepository(session).save_external_result(
                    ctx.request_id, ctx.token, external, self._ctx.clock.now()
                )
        except SQLAlchemyError as error:
            _log.error("external_result_save_failed", error_type=type(error).__name__)
            return False

    async def _resume(
        self, ctx: ExecutionContext, body: dict[str, Any], external: dict[str, Any]
    ) -> ApprovalOutcome:
        """X投稿は成功済み。X APIを呼ばず、保存済みの結果でDB保存だけを再実行する。"""
        request = validate_model(XPostRequest, body)
        try:
            published = published_from_external_result(request, str(ctx.key), external)
        except ValueError:
            # ValidationErrorは入力値を含み得るため、保存済み本文などをログへ渡さない。
            _log.error("invalid_external_result")
            return await self._save_failed(ctx)
        try:
            embedding = await self._embed(published.body)
        except AppError:
            return await self._save_failed(ctx)
        return await self._save_with_retry(ctx, request.campaign_id, published, embedding)

    async def _save_with_retry(
        self,
        ctx: ExecutionContext,
        campaign_id: int,
        published: PublishedPost,
        embedding: list[float],
    ) -> ApprovalOutcome:
        """DB保存を最大3回、指数バックオフで再試行する。失敗が続けばLeaseを即時失効させる。"""
        for attempt in range(1, DB_SAVE_MAX_ATTEMPTS + 1):
            try:
                return await self._save(ctx, campaign_id, published, embedding)
            except SQLAlchemyError as error:
                _log.error("post_save_failed", attempt=attempt, error_type=type(error).__name__)
                if attempt < DB_SAVE_MAX_ATTEMPTS:
                    await self._ctx.sleep(DB_SAVE_BACKOFF_BASE_SECONDS * 2 ** (attempt - 1))
        return await self._save_failed(ctx)

    async def _save(
        self,
        ctx: ExecutionContext,
        campaign_id: int,
        published: PublishedPost,
        embedding: list[float],
    ) -> ApprovalOutcome:
        """投稿・Embedding・UTM・計測予定・成功の確定を同一Transactionで保存する。"""
        now = self._ctx.clock.now()
        async with self._ctx.session_factory() as session, session.begin():
            body = await insert_published_post(
                session,
                ctx,
                campaign_id,
                published,
                embedding,
                response_turn_id=ctx.turn_id,
            )
            await ApprovalStore(session, now).complete(
                ctx,
                status=ApiIdempotencyStatus.SUCCEEDED,
                http_status=201,
                body=body,
                error=None,
            )
        return ApprovalOutcome(201, body)

    async def _save_failed(self, ctx: ExecutionContext) -> ApprovalOutcome:
        """`X_POST_SAVE_FAILED`: Leaseを即時失効させ、`processing` のまま外部結果を保持する。

        確定Responseではないため、冪等性レコードには保存しない。API実行Turnも終端にしない。
        """
        async with self._ctx.session_factory() as session, session.begin():
            expired = await IdempotencyRepository(session).expire_lease(
                ctx.request_id, ctx.token, self._ctx.clock.now()
            )
            if not expired:
                raise LeaseLostError
        error = AppError("X_POST_SAVE_FAILED", agent_turn_id=ctx.turn_id)
        return ApprovalOutcome(error.status_code, error_body(error))

    async def _outcome_unknown(self, ctx: ExecutionContext) -> ApprovalOutcome:
        error = AppError("X_POST_OUTCOME_UNKNOWN")
        return await self._fail(ctx, error, ApiIdempotencyStatus.OUTCOME_UNKNOWN)

    async def _fail(
        self, ctx: ExecutionContext, error: AppError, status: ApiIdempotencyStatus
    ) -> ApprovalOutcome:
        """マスク済みエラー・Turn完了・`failed`（結果不明は `outcome_unknown`）を保存する。"""
        failed = AppError(
            error.code,
            error.message,
            agent_turn_id=ctx.turn_id,
            retryable=error.retryable,
            field_errors=error.field_errors,
        )
        body = error_body(failed)
        now = self._ctx.clock.now()
        async with self._ctx.session_factory() as session, session.begin():
            await ApprovalStore(session, now).complete(
                ctx,
                status=status,
                http_status=failed.status_code,
                body=body,
                error=failed,
            )
        return ApprovalOutcome(failed.status_code, body)
