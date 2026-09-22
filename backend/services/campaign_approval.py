"""施策登録・更新（承認API。API_DESIGN 4.1）。"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from clients.errors import EmbeddingError
from core.errors import AppError, LeaseLostError
from core.logging import get_logger, safe_error_text
from domain.campaign_rules import CampaignContent, campaign_field_errors
from domain.constants import IN_PROGRESS_RETRY_AFTER_SECONDS
from domain.enums import ApiIdempotencyStatus, ApiOperation
from domain.requests import CampaignUpsertRequest
from domain.search_text import build_campaign_search_text, content_hash
from domain.timefmt import format_utc
from repositories.campaigns import CampaignRepository
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


class _ConflictError(Exception):
    """保存時の競合（`updated_at` の不一致）。"""


@dataclass(frozen=True)
class _Plan:
    """検証と事前の外部呼び出しを終えた、保存する内容。"""

    request: CampaignUpsertRequest
    content: CampaignContent
    content_hash: str
    embedding: list[float] | None


class CampaignApprovalService:
    """Agentの提案を承認した施策のフォーム値を、新規保存または全項目上書きで保存する。"""

    def __init__(self, ctx: ServiceContext) -> None:
        """サービスの依存を受け取る。"""
        self._ctx = ctx
        self._executor = ApprovalExecutor(ctx)

    async def upsert(
        self, auth: AuthContext, session_id: int, body_loader: BodyLoader, key_header: str | None
    ) -> ApprovalOutcome:
        """施策を登録または更新する。

        Raises:
            AppError: 履歴へ保存しないエラー（親Session・Body・キー・処理中など）。
        """
        prepared = await self._executor.prepare(
            auth, session_id, ApiOperation.UPSERT_CAMPAIGN, body_loader, key_header
        )
        if isinstance(prepared, ApprovalOutcome):
            return prepared
        try:
            return await self._run(prepared.execution, prepared.body)
        except LeaseLostError:
            raise AppError(
                "IDEMPOTENCY_REQUEST_IN_PROGRESS",
                retry_after_seconds=IN_PROGRESS_RETRY_AFTER_SECONDS,
            ) from None

    async def _run(self, ctx: ExecutionContext, body: dict[str, Any]) -> ApprovalOutcome:
        try:
            plan = await self._plan(ctx, body)
        except AppError as error:
            return await self._fail(ctx, error)
        try:
            return await self._save(ctx, plan)
        except _ConflictError:
            return await self._fail(ctx, AppError("CAMPAIGN_CONFLICT"))
        except SQLAlchemyError as error:
            _log.error("campaign_upsert_save_failed", error=safe_error_text(error))
            code = "CAMPAIGN_SAVE_FAILED" if plan.request.id is None else "CAMPAIGN_UPDATE_FAILED"
            return await self._fail(ctx, AppError(code))

    async def _plan(self, ctx: ExecutionContext, body: dict[str, Any]) -> _Plan:
        """Schema・業務条件・競合を検証し、必要ならEmbeddingを生成する（Transactionの外）。"""
        request = validate_model(CampaignUpsertRequest, body)
        content = CampaignContent(
            request.title,
            request.target_profile,
            request.background,
            request.objective,
            request.plan,
        )
        field_errors = campaign_field_errors(content)
        if field_errors:
            raise AppError("INVALID_CAMPAIGN", field_errors=field_errors)
        stored_hash: str | None = None
        if request.id is not None:
            async with self._ctx.session_factory() as session:
                repository = CampaignRepository(session)
                existing = await repository.get(ctx.auth.company_id, request.id)
                if existing is None:
                    raise AppError("CAMPAIGN_NOT_FOUND")
                # Embedding生成の前に競合を検出する。timestamptz の値として比較する。
                if existing.updated_at != request.expected_updated_at:
                    raise AppError("CAMPAIGN_CONFLICT")
                stored_hash = await repository.get_embedding_hash(request.id)
        search_text = build_campaign_search_text(content)
        digest = content_hash(search_text)
        embedding: list[float] | None = None
        if stored_hash != digest:
            embedding = await self._embed(search_text)
        return _Plan(request, content, digest, embedding)

    async def _embed(self, search_text: str) -> list[float]:
        try:
            return await self._ctx.embedding.embed(search_text)
        except EmbeddingError as error:
            _log.warning("campaign_embedding_failed", error=safe_error_text(error))
            raise AppError("EMBEDDING_FAILED") from None

    async def _save(self, ctx: ExecutionContext, plan: _Plan) -> ApprovalOutcome:
        """施策・Embedding・API Result・Turn完了・冪等性の確定を、同一Transactionで保存する。"""
        now = self._ctx.clock.now()
        request, content = plan.request, plan.content
        async with self._ctx.session_factory() as session, session.begin():
            repository = CampaignRepository(session)
            if request.id is None:
                campaign = await repository.insert(
                    ctx.auth.company_id, ctx.auth.marketer_id, content, now
                )
                campaign_id, http_status = campaign.id, 201
                data: dict[str, Any] = {
                    "id": campaign_id,
                    "agent_turn_id": ctx.turn_id,
                    "title": content.title,
                    "created_at": format_utc(now),
                }
            else:
                assert request.expected_updated_at is not None  # noqa: S101
                updated = await repository.update_if_unchanged(
                    ctx.auth.company_id, request.id, request.expected_updated_at, content, now
                )
                if not updated:
                    raise _ConflictError
                campaign_id, http_status = request.id, 200
                data = {
                    "id": campaign_id,
                    "agent_turn_id": ctx.turn_id,
                    "title": content.title,
                    "updated_at": format_utc(now),
                }
            if plan.embedding is not None:
                await repository.upsert_embedding(
                    campaign_id, plan.embedding, plan.content_hash, now
                )
            body = success_body(data)
            await ApprovalStore(session, now).complete(
                ctx,
                status=ApiIdempotencyStatus.SUCCEEDED,
                http_status=http_status,
                body=body,
                error=None,
            )
        return ApprovalOutcome(http_status, body)

    async def _fail(self, ctx: ExecutionContext, error: AppError) -> ApprovalOutcome:
        """マスク済みエラー・Turn完了・`failed` の確定を、同一Transactionで保存する。"""
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
                status=ApiIdempotencyStatus.FAILED,
                http_status=failed.status_code,
                body=body,
                error=failed,
            )
        return ApprovalOutcome(failed.status_code, body)
