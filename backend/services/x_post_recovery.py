"""X投稿の結果不明照合と、X成功後に放置されたDB保存の運用復旧。"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from clients.errors import EmbeddingError
from core.canonical import request_hash
from core.errors import AppError, LeaseLostError
from domain.enums import (
    AgentContentSource,
    AgentItemType,
    AgentTurnStatus,
    ApiIdempotencyStatus,
    ApiOperation,
)
from domain.requests import XPostRequest
from domain.search_text import build_post_search_text
from domain.timefmt import format_utc
from domain.tracking import build_tracking_url
from models import AgentItem, ApiIdempotencyRequest, Marketer
from repositories.agent import SessionRepository, TurnRepository
from repositories.idempotency import IdempotencyRepository
from services.approval import ExecutionContext, error_body
from services.context import AuthContext, ServiceContext
from services.validation import validate_model
from services.x_post_approval import (
    PublishedPost,
    XPostApprovalService,
    insert_published_post,
)


class XPostRecoveryError(Exception):
    """運用復旧を安全に実行できないことを示す、出力可能なError。"""


@dataclass(frozen=True)
class RecoveryCandidate:
    """機密Payloadを含まない復旧対象Metadata。"""

    request_id: int
    company_id: int
    marketer_id: int
    session_id: int
    status: str
    recovery: Literal["manual_reconciliation", "resume_persistence"]
    external_effect_started: bool
    external_succeeded: bool
    lease_expired: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class RecoveryResult:
    """機密Payloadを含まない復旧結果。"""

    request_id: int
    status: str
    audit_turn_id: int | None = None
    post_id: int | None = None


class XPostRecoveryService:
    """公開HTTP APIから分離したX投稿の運用復旧Service。"""

    def __init__(self, ctx: ServiceContext) -> None:
        """実行Contextを受け取る。"""
        self._ctx = ctx

    async def list_candidates(
        self, *, limit: int = 100, company_id: int | None = None
    ) -> list[RecoveryCandidate]:
        """未解決Requestを安全なMetadataだけで列挙する。"""
        if not 1 <= limit <= 1000:
            raise XPostRecoveryError("limit must be between 1 and 1000")
        now = self._ctx.clock.now()
        async with self._ctx.session_factory() as session:
            rows = await IdempotencyRepository(session).list_x_recovery_candidates(
                now=now, limit=limit, company_id=company_id
            )
            owners = (
                await session.execute(
                    select(Marketer.id, Marketer.company_id).where(
                        Marketer.id.in_({row.marketer_id for row in rows})
                    )
                )
            ).all()
            company_by_marketer: dict[int, int] = {}
            for marketer_id, owner_company_id in owners:
                company_by_marketer[marketer_id] = owner_company_id
        return [self._metadata(row, company_by_marketer[row.marketer_id], now) for row in rows]

    async def inspect(self, request_id: int) -> RecoveryCandidate:
        """復旧対象を1件確認する。Payloadは返さない。"""
        now = self._ctx.clock.now()
        async with self._ctx.session_factory() as session:
            row = await IdempotencyRepository(session).get(request_id)
            if row is None or not self._is_candidate(row, now):
                raise XPostRecoveryError("request is not an unresolved X recovery candidate")
            marketer = await session.get(Marketer, row.marketer_id)
            if marketer is None:
                raise XPostRecoveryError("request owner is unavailable")
            return self._metadata(row, marketer.company_id, now)

    async def resolve_posted(
        self,
        request_id: int,
        *,
        x_post_id: str,
        published_at: datetime,
        request_body: dict[str, Any] | None = None,
    ) -> RecoveryResult:
        """X公開成功を確認した結果で、結果不明Requestを一度だけ成功へ確定する。"""
        if not x_post_id or len(x_post_id) > 255 or published_at.tzinfo is None:
            raise XPostRecoveryError("posted evidence is invalid")
        row, auth = await self._load_unknown_owner(request_id)
        async with self._ctx.session_factory() as session:
            request = await self._load_original_request(session, row, supplied=request_body)
        tracking = build_tracking_url(
            request.landing_url, request.campaign_id, str(row.idempotency_key)
        )
        published = PublishedPost(request.body, x_post_id, published_at, tracking)
        try:
            embedding = await self._ctx.embedding.embed(build_post_search_text(request.body))
        except EmbeddingError:
            raise XPostRecoveryError("embedding generation failed; no data was changed") from None

        now = self._ctx.clock.now()
        try:
            async with self._ctx.session_factory() as session, session.begin():
                await self._lock_parent_session(session, row)
                current = await IdempotencyRepository(session).get_for_update(request_id)
                if (
                    current is None
                    or current.status != ApiIdempotencyStatus.OUTCOME_UNKNOWN
                    or current.agent_turn_id is None
                ):
                    raise XPostRecoveryError("request was already resolved by another operator")
                audit_turn_id = await self._create_audit_turn(
                    session,
                    current,
                    now,
                    resolution="posted",
                    x_post_id=x_post_id,
                    published_at=published_at,
                )
                ctx = self._execution(current, auth)
                body = await insert_published_post(
                    session,
                    ctx,
                    request.campaign_id,
                    published,
                    embedding,
                    response_turn_id=current.agent_turn_id,
                )
                resolved = await IdempotencyRepository(session).resolve_unknown(
                    request_id,
                    status=ApiIdempotencyStatus.SUCCEEDED,
                    http_status=201,
                    response_body=body,
                    now=now,
                )
                if not resolved:
                    raise XPostRecoveryError("request was already resolved by another operator")
                await self._finish_audit(session, current, audit_turn_id, now, success=True)
                post_id = int(body["data"]["post_id"])
        except SQLAlchemyError:
            raise XPostRecoveryError("database persistence failed; no data was changed") from None
        return RecoveryResult(request_id, ApiIdempotencyStatus.SUCCEEDED, audit_turn_id, post_id)

    async def resolve_not_posted(self, request_id: int) -> RecoveryResult:
        """Xへ未公開と確認した結果で、結果不明Requestを一度だけ失敗へ確定する。"""
        row, _auth = await self._load_unknown_owner(request_id)
        now = self._ctx.clock.now()
        async with self._ctx.session_factory() as session, session.begin():
            await self._lock_parent_session(session, row)
            current = await IdempotencyRepository(session).get_for_update(request_id)
            if (
                current is None
                or current.status != ApiIdempotencyStatus.OUTCOME_UNKNOWN
                or current.agent_turn_id is None
            ):
                raise XPostRecoveryError("request was already resolved by another operator")
            audit_turn_id = await self._create_audit_turn(
                session, current, now, resolution="not_posted"
            )
            error = AppError("X_POST_FAILED", agent_turn_id=current.agent_turn_id)
            body = error_body(error)
            resolved = await IdempotencyRepository(session).resolve_unknown(
                request_id,
                status=ApiIdempotencyStatus.FAILED,
                http_status=error.status_code,
                response_body=body,
                now=now,
            )
            if not resolved:
                raise XPostRecoveryError("request was already resolved by another operator")
            await self._finish_audit(session, current, audit_turn_id, now, success=False)
        return RecoveryResult(request_id, ApiIdempotencyStatus.FAILED, audit_turn_id)

    async def resume_persistence(
        self, request_id: int, *, request_body: dict[str, Any] | None = None
    ) -> RecoveryResult:
        """期限切れかつX成功結果保存済みのRequestを、Xを呼ばずDB保存だけ再開する。"""
        now = self._ctx.clock.now()
        async with self._ctx.session_factory() as session:
            row = await IdempotencyRepository(session).get(request_id)
            if row is None or not self._is_resumable(row, now):
                raise XPostRecoveryError("request is not an expired persistence recovery candidate")
            request = await self._load_original_request(session, row, supplied=request_body)
            marketer = await session.get(Marketer, row.marketer_id)
            if marketer is None or row.agent_turn_id is None or row.external_result is None:
                raise XPostRecoveryError("request recovery metadata is incomplete")
            auth = AuthContext(marketer.id, marketer.company_id, marketer.user_id, "")

        token = self._ctx.new_uuid()
        async with self._ctx.session_factory() as session, session.begin():
            await self._lock_parent_session(session, row)
            current = await IdempotencyRepository(session).get_for_update(request_id)
            if current is None or not self._is_resumable(current, now):
                raise XPostRecoveryError("request was claimed by another worker")
            claimed = await IdempotencyRepository(session).reacquire(
                current,
                new_token=token,
                new_lease_expires_at=now + timedelta(seconds=self._ctx.settings.lease_seconds),
                now=now,
            )
            if not claimed:
                raise XPostRecoveryError("request was claimed by another worker")
            turn_id = current.agent_turn_id
            external = current.external_result
        assert turn_id is not None and external is not None  # noqa: S101 - 上で検証済み
        ctx = ExecutionContext(
            ApiOperation.PUBLISH_X_POST,
            auth,
            row.session_id,
            row.idempotency_key,
            request_id,
            token,
            turn_id,
            external_result=external,
        )
        try:
            outcome = await XPostApprovalService(self._ctx).resume_persistence(
                ctx, request.model_dump(mode="json"), external
            )
        except LeaseLostError:
            raise XPostRecoveryError("request was claimed by another worker") from None
        if outcome.http_status != 201:
            raise XPostRecoveryError(
                "persistence recovery did not complete; request remains retryable"
            )
        return RecoveryResult(
            request_id,
            ApiIdempotencyStatus.SUCCEEDED,
            post_id=int(outcome.body["data"]["post_id"]),
        )

    async def _load_unknown_owner(
        self, request_id: int
    ) -> tuple[ApiIdempotencyRequest, AuthContext]:
        async with self._ctx.session_factory() as session:
            row = await IdempotencyRepository(session).get(request_id)
            if row is None or row.status != ApiIdempotencyStatus.OUTCOME_UNKNOWN:
                raise XPostRecoveryError("request is not awaiting manual reconciliation")
            marketer = await session.get(Marketer, row.marketer_id)
            if marketer is None:
                raise XPostRecoveryError("request owner is unavailable")
            auth = AuthContext(marketer.id, marketer.company_id, marketer.user_id, "")
            return row, auth

    @staticmethod
    async def _load_original_request(
        session: AsyncSession,
        row: ApiIdempotencyRequest,
        *,
        supplied: dict[str, Any] | None = None,
    ) -> XPostRequest:
        raw: object = supplied
        if raw is None:
            if row.agent_turn_id is None:
                raise XPostRecoveryError("original request metadata is incomplete")
            stmt = select(AgentItem.content).where(
                AgentItem.agent_turn_id == row.agent_turn_id,
                AgentItem.idempotency_key == f"approval-request:{row.idempotency_key}",
            )
            content = (await session.execute(stmt)).scalar_one_or_none()
            raw = content.get("action", {}).get("request") if isinstance(content, dict) else None
        if not isinstance(raw, dict) or request_hash(raw) != row.request_hash:
            raise XPostRecoveryError(
                "original request cannot be safely reconstructed; provide verified JSON via stdin"
            )
        try:
            return validate_model(XPostRequest, raw)
        except AppError:
            raise XPostRecoveryError("original request cannot be safely reconstructed") from None

    async def _lock_parent_session(self, session: AsyncSession, row: ApiIdempotencyRequest) -> None:
        parent = await SessionRepository(session).get_parent(
            row.marketer_id, row.session_id, lock=True
        )
        if parent is None:
            raise XPostRecoveryError("parent session is unavailable")

    async def _create_audit_turn(
        self,
        session: AsyncSession,
        row: ApiIdempotencyRequest,
        now: datetime,
        *,
        resolution: Literal["posted", "not_posted"],
        x_post_id: str | None = None,
        published_at: datetime | None = None,
    ) -> int:
        turns = TurnRepository(session)
        turn = await turns.create_turn(row.session_id, now)
        content: dict[str, Any] = {
            "kind": "x_post_manual_reconciliation",
            "text": "X投稿の手動照合を実施しました。",
            "request_id": row.id,
            "resolution": resolution,
        }
        if x_post_id is not None and published_at is not None:
            content.update({"x_post_id": x_post_id, "published_at": format_utc(published_at)})
        await turns.append_item(
            turn.id,
            key="reconciliation-decision",
            item_type=AgentItemType.USER_MESSAGE,
            source=AgentContentSource.SYSTEM,
            content=content,
            now=now,
        )
        return turn.id

    async def _finish_audit(
        self,
        session: AsyncSession,
        row: ApiIdempotencyRequest,
        turn_id: int,
        now: datetime,
        *,
        success: bool,
    ) -> None:
        turns = TurnRepository(session)
        await turns.append_item(
            turn_id,
            key="reconciliation-result",
            item_type=AgentItemType.ASSISTANT_MESSAGE,
            source=AgentContentSource.SYSTEM,
            content={
                "kind": "api_result",
                "text": "X投稿の手動照合が完了しました。",
                "operation": ApiOperation.PUBLISH_X_POST,
                "success": success,
                "error": (None if success else error_body(AppError("X_POST_FAILED"))["error"]),
                "request_id": row.id,
            },
            now=now,
        )
        await turns.finish_turn(turn_id, status=AgentTurnStatus.COMPLETED, now=now)
        await SessionRepository(session).touch(row.session_id, now)

    @staticmethod
    def _execution(row: ApiIdempotencyRequest, auth: AuthContext) -> ExecutionContext:
        assert row.agent_turn_id is not None  # noqa: S101 - unknown生成時のDB契約
        return ExecutionContext(
            ApiOperation.PUBLISH_X_POST,
            auth,
            row.session_id,
            row.idempotency_key,
            row.id,
            row.execution_token,
            row.agent_turn_id,
        )

    @staticmethod
    def _is_resumable(row: ApiIdempotencyRequest, now: datetime) -> bool:
        return (
            row.operation == ApiOperation.PUBLISH_X_POST
            and row.status == ApiIdempotencyStatus.PROCESSING
            and row.lease_expires_at <= now
            and row.external_result is not None
        )

    @classmethod
    def _is_candidate(cls, row: ApiIdempotencyRequest, now: datetime) -> bool:
        return row.operation == ApiOperation.PUBLISH_X_POST and (
            row.status == ApiIdempotencyStatus.OUTCOME_UNKNOWN or cls._is_resumable(row, now)
        )

    @classmethod
    def _metadata(
        cls, row: ApiIdempotencyRequest, company_id: int, now: datetime
    ) -> RecoveryCandidate:
        resumable = cls._is_resumable(row, now)
        return RecoveryCandidate(
            request_id=row.id,
            company_id=company_id,
            marketer_id=row.marketer_id,
            session_id=row.session_id,
            status=row.status,
            recovery="resume_persistence" if resumable else "manual_reconciliation",
            external_effect_started=row.external_effect_started_at is not None,
            external_succeeded=row.external_result is not None,
            lease_expired=row.lease_expires_at <= now,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
