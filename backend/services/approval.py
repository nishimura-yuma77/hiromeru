"""承認API（施策upsert・X投稿）に共通する、冪等性・API実行Turn・API Resultの処理。

API_DESIGN 2.2〜2.4 に従う。処理の順序は次のとおり。
1. 親Sessionの所有権（404）
2. Request Bodyの安全な解析とマスク（400）
3. Idempotency-Key の検証（400）
4. 実行権の取得（Session行のロック → 冪等性行のロックと予約または再開の判定）
5. API実行Turnの作成と、最終Requestの保存
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.canonical import request_hash
from core.errors import AppError, LeaseLostError
from core.masking import mask_json
from domain.constants import IN_PROGRESS_RETRY_AFTER_SECONDS
from domain.enums import (
    AgentContentSource,
    AgentItemType,
    AgentTurnStatus,
    ApiIdempotencyStatus,
    ApiOperation,
)
from models import ApiIdempotencyRequest
from repositories.agent import SessionRepository, TurnRepository
from repositories.idempotency import IdempotencyRepository
from services.context import AuthContext, ServiceContext
from services.validation import parse_json_object


@dataclass(frozen=True)
class ApprovalOutcome:
    """承認APIのHTTP応答。`body` は共通のResponse形式（2.5、2.6）。"""

    http_status: int
    body: dict[str, Any]
    retry_after_seconds: int | None = None


@dataclass(frozen=True)
class ExecutionContext:
    """実行権を得たRequestの文脈。"""

    operation: ApiOperation
    auth: AuthContext
    session_id: int
    key: uuid.UUID
    request_id: int
    token: uuid.UUID
    turn_id: int
    # X投稿だけ: 前回のRequestがX投稿の成功結果を保存済みで、DB保存だけを再開する。
    external_result: dict[str, Any] | None = None


@dataclass(frozen=True)
class Prepared:
    """実行権を得た承認Request。"""

    execution: ExecutionContext
    body: dict[str, Any]


def success_body(data: dict[str, Any]) -> dict[str, Any]:
    """成功Response（2.5）。"""
    return {"success": True, "data": data, "error": None}


def error_body(error: AppError) -> dict[str, Any]:
    """エラーResponse（2.6）。"""
    return {
        "success": False,
        "data": None,
        "error": error.serialize(),
    }


def parse_idempotency_key(header: str | None) -> uuid.UUID:
    """Idempotency-Key をUUIDとして検証する。

    Raises:
        AppError: ない、またはUUID形式でない場合（INVALID_IDEMPOTENCY_KEY）。
    """
    if not header:
        raise AppError("INVALID_IDEMPOTENCY_KEY")
    try:
        return uuid.UUID(header.strip())
    except ValueError:
        raise AppError("INVALID_IDEMPOTENCY_KEY") from None


class ApprovalStore:
    """承認APIの確定処理。1つのTransaction（`AsyncSession`）の中で使う。"""

    def __init__(self, session: AsyncSession, now: datetime) -> None:
        """Transactionと、確定に使う時刻を受け取る。"""
        self._idempotency = IdempotencyRepository(session)
        self._turns = TurnRepository(session)
        self._now = now

    async def complete(
        self,
        ctx: ExecutionContext,
        *,
        status: ApiIdempotencyStatus,
        http_status: int,
        body: dict[str, Any],
        error: AppError | None,
        require_lease: bool = True,
    ) -> None:
        """API Resultを保存し、Turnを完了して、冪等性レコードを確定する（同一Transaction）。

        Raises:
            LeaseLostError: 実行Tokenまたは有効なLeaseの条件を満たさない場合。
        """
        finalized = await self._idempotency.finalize(
            ctx.request_id,
            ctx.token,
            status=status,
            http_status=http_status,
            response_body=body,
            now=self._now,
            require_lease=require_lease,
        )
        if not finalized:
            raise LeaseLostError
        await self.save_result_and_finish_turn(
            ctx.turn_id, ctx.key, ctx.operation, success=error is None, error=error
        )

    async def save_result_and_finish_turn(
        self,
        turn_id: int,
        key: uuid.UUID,
        operation: ApiOperation,
        *,
        success: bool,
        error: AppError | None,
    ) -> None:
        """`api_result` を保存し、API実行Turnを完了する。"""
        content: dict[str, Any] = {
            "kind": "api_result",
            "operation": operation.value,
            "success": success,
            "error": None
            if error is None
            else {
                "code": error.code,
                "message": error.message,
                "retryable": error.retryable,
                "field_errors": error.field_errors,
            },
        }
        await self._turns.append_item(
            turn_id,
            key=f"approval-result:{key}",
            item_type=AgentItemType.ASSISTANT_MESSAGE,
            source=AgentContentSource.SYSTEM,
            content=content,
            now=self._now,
        )
        await self._turns.finish_turn(turn_id, status=AgentTurnStatus.COMPLETED, now=self._now)


class ApprovalExecutor:
    """実行権の取得までを担う。"""

    def __init__(self, ctx: ServiceContext) -> None:
        """サービスの依存を受け取る。"""
        self._ctx = ctx

    async def prepare(
        self,
        auth: AuthContext,
        session_id: int,
        operation: ApiOperation,
        raw_body: bytes,
        key_header: str | None,
    ) -> Prepared | ApprovalOutcome:
        """実行権を取得する。保存済みResponseの再返却では `ApprovalOutcome` を返す。

        Raises:
            AppError: 親Session・Body・Idempotency-Keyの不正、キー再利用、処理中。
        """
        # 1. 親Sessionの所有権。存在しない・他人・子Sessionは区別しない。
        async with self._ctx.session_factory() as session:
            if await SessionRepository(session).get_parent(auth.marketer_id, session_id) is None:
                raise AppError("AGENT_SESSION_NOT_FOUND")
        # 2. 安全な解析とマスク。3. Idempotency-Key。
        body = parse_json_object(raw_body)
        key = parse_idempotency_key(key_header)
        return await self._claim(auth, session_id, operation, key, body)

    async def _claim(
        self,
        auth: AuthContext,
        session_id: int,
        operation: ApiOperation,
        key: uuid.UUID,
        body: dict[str, Any],
    ) -> Prepared | ApprovalOutcome:
        digest = request_hash(body)
        now = self._ctx.clock.now()
        async with self._ctx.session_factory() as session, session.begin():
            sessions = SessionRepository(session)
            idempotency = IdempotencyRepository(session)
            # Session行 → Advisory Lock → 冪等性行の順にロックする（常に同じ順序）。
            agent_session = await sessions.get_parent(auth.marketer_id, session_id, lock=True)
            if agent_session is None:
                raise AppError("AGENT_SESSION_NOT_FOUND")
            if operation == ApiOperation.PUBLISH_X_POST:
                await idempotency.advisory_lock(f"publish_x_post:{auth.marketer_id}:{digest}")
            row = await idempotency.find_for_update(auth.marketer_id, operation, key)
            if row is None:
                if agent_session.archived_at is not None:
                    raise AppError("AGENT_SESSION_NOT_FOUND")
                row = await idempotency.reserve(
                    marketer_id=auth.marketer_id,
                    session_id=session_id,
                    operation=operation,
                    key=key,
                    request_hash=digest,
                    token=self._ctx.new_uuid(),
                    lease_expires_at=now + timedelta(seconds=self._ctx.settings.lease_seconds),
                    now=now,
                )
                if row is not None:
                    return await self._start_new(session, auth, row, operation, key, body, now)
                # 別Sessionからの同じキーの同時Requestに負けた。勝った行の確定後に再判定する。
                row = await idempotency.find_for_update(auth.marketer_id, operation, key)
                if row is None:
                    raise AppError(
                        "IDEMPOTENCY_REQUEST_IN_PROGRESS",
                        retry_after_seconds=IN_PROGRESS_RETRY_AFTER_SECONDS,
                    )
            return await self._decide_existing(
                session, auth, row, (session_id, operation, key, digest), body, now
            )

    async def _start_new(
        self,
        session: AsyncSession,
        auth: AuthContext,
        row: ApiIdempotencyRequest,
        operation: ApiOperation,
        key: uuid.UUID,
        body: dict[str, Any],
        now: datetime,
    ) -> Prepared | ApprovalOutcome:
        turn_id = await self._create_api_turn(session, row, operation, key, body, now)
        execution = ExecutionContext(
            operation, auth, row.session_id, key, row.id, row.execution_token, turn_id
        )
        if operation == ApiOperation.PUBLISH_X_POST and await IdempotencyRepository(
            session
        ).has_unresolved_duplicate(auth.marketer_id, row.request_hash, exclude_id=row.id):
            # 別キーに、同じ内容の処理中・結果不明のX投稿がある。候補を failed で確定する。
            error = AppError("X_POST_UNRESOLVED", agent_turn_id=turn_id)
            outcome = ApprovalOutcome(error.status_code, error_body(error))
            await ApprovalStore(session, now).complete(
                execution,
                status=ApiIdempotencyStatus.FAILED,
                http_status=outcome.http_status,
                body=outcome.body,
                error=error,
            )
            return outcome
        return Prepared(execution, body)

    async def _create_api_turn(
        self,
        session: AsyncSession,
        row: ApiIdempotencyRequest,
        operation: ApiOperation,
        key: uuid.UUID,
        body: dict[str, Any],
        now: datetime,
    ) -> int:
        """API実行Turnを作成し、マスク済みの最終Requestを保存する（2.4）。"""
        turns = TurnRepository(session)
        turn = await turns.create_turn(row.session_id, now)
        await turns.append_item(
            turn.id,
            key=f"approval-request:{key}",
            item_type=AgentItemType.USER_MESSAGE,
            source=AgentContentSource.USER_INPUT,
            content={
                "action": {"id": str(key), "type": operation.value, "request": mask_json(body)}
            },
            now=now,
        )
        await SessionRepository(session).touch(row.session_id, now)
        await IdempotencyRepository(session).attach_turn(row.id, turn.id, now)
        return turn.id

    async def _decide_existing(
        self,
        session: AsyncSession,
        auth: AuthContext,
        row: ApiIdempotencyRequest,
        requested: tuple[int, ApiOperation, uuid.UUID, str],
        body: dict[str, Any],
        now: datetime,
    ) -> Prepared | ApprovalOutcome:
        """既存の冪等性行に対する処理を、2.3の表に従って決める。"""
        session_id, operation, key, digest = requested
        if row.session_id != session_id or row.request_hash != digest:
            raise AppError("IDEMPOTENCY_KEY_REUSED")
        if row.status != ApiIdempotencyStatus.PROCESSING:
            # succeeded・failed・outcome_unknown: 保存済みのResponseをそのまま返す。
            assert row.http_status is not None and row.response_body is not None  # noqa: S101
            return ApprovalOutcome(row.http_status, row.response_body)
        if row.lease_expires_at > now:
            raise AppError(
                "IDEMPOTENCY_REQUEST_IN_PROGRESS",
                retry_after_seconds=IN_PROGRESS_RETRY_AFTER_SECONDS,
            )
        idempotency = IdempotencyRepository(session)
        started = row.external_effect_started_at is not None
        if operation == ApiOperation.PUBLISH_X_POST and started and row.external_result is None:
            return await self._recover_unknown(session, row, key, now)
        reacquired = await idempotency.reacquire(
            row,
            new_token=self._ctx.new_uuid(),
            new_lease_expires_at=now + timedelta(seconds=self._ctx.settings.lease_seconds),
            now=now,
        )
        if not reacquired:
            raise AppError(
                "IDEMPOTENCY_REQUEST_IN_PROGRESS",
                retry_after_seconds=IN_PROGRESS_RETRY_AFTER_SECONDS,
            )
        await session.refresh(row)
        turn_id = row.agent_turn_id
        if turn_id is None:
            turn_id = await self._create_api_turn(session, row, operation, key, body, now)
        return Prepared(
            ExecutionContext(
                operation,
                auth,
                row.session_id,
                key,
                row.id,
                row.execution_token,
                turn_id,
                external_result=row.external_result,
            ),
            body,
        )

    async def _recover_unknown(
        self,
        session: AsyncSession,
        row: ApiIdempotencyRequest,
        key: uuid.UUID,
        now: datetime,
    ) -> ApprovalOutcome:
        """X API送信後に結果を保存できないまま中断されたRequestを `outcome_unknown` へ確定する。"""
        error = AppError("X_POST_OUTCOME_UNKNOWN", agent_turn_id=row.agent_turn_id)
        body = error_body(error)
        recovered = await IdempotencyRepository(session).recover_unknown(
            row, http_status=error.status_code, response_body=body, now=now
        )
        if not recovered:
            raise AppError(
                "IDEMPOTENCY_REQUEST_IN_PROGRESS",
                retry_after_seconds=IN_PROGRESS_RETRY_AFTER_SECONDS,
            )
        if row.agent_turn_id is not None:
            await ApprovalStore(session, now).save_result_and_finish_turn(
                row.agent_turn_id, key, ApiOperation.PUBLISH_X_POST, success=False, error=error
            )
        return ApprovalOutcome(error.status_code, body)
