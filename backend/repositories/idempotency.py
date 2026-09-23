"""API冪等性Requestのリポジトリ（API_DESIGN 2.3）。"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from domain.enums import ApiIdempotencyStatus, ApiOperation
from models import ApiIdempotencyRequest


class IdempotencyRepository:
    """冪等性レコードのDBアクセス。

    実行権（Lease・Fencing Token）を伴う更新は、すべて条件付きUPDATEで行い、
    更新できなければ False を返す。呼び出し側が `LeaseLostError` へ変換する。
    """

    def __init__(self, session: AsyncSession) -> None:
        """セッションを受け取る。"""
        self._session = session

    async def advisory_lock(self, key: str) -> None:
        """Transaction-scopedのAdvisory Lockを取得する。

        セッション単位のロックはNeonのプール経由で使えないため、xact版を使う（BE_STD 17.2）。
        """
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key}
        )

    async def find_for_update(
        self, marketer_id: int, operation: ApiOperation, key: uuid.UUID
    ) -> ApiIdempotencyRequest | None:
        """マーケター・操作種別・キーで行をロックして取得する。"""
        stmt = (
            select(ApiIdempotencyRequest)
            .where(
                ApiIdempotencyRequest.marketer_id == marketer_id,
                ApiIdempotencyRequest.operation == operation,
                ApiIdempotencyRequest.idempotency_key == key,
            )
            .with_for_update()
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get(self, request_id: int) -> ApiIdempotencyRequest | None:
        """IDで取得する。"""
        return await self._session.get(ApiIdempotencyRequest, request_id)

    async def get_for_update(self, request_id: int) -> ApiIdempotencyRequest | None:
        """IDで行をロックして取得する。"""
        stmt = (
            select(ApiIdempotencyRequest)
            .where(ApiIdempotencyRequest.id == request_id)
            .with_for_update()
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_x_recovery_candidates(
        self, *, now: datetime, limit: int, company_id: int | None = None
    ) -> list[ApiIdempotencyRequest]:
        """結果不明と、X成功後に保存待ちの期限切れRequestを列挙する。"""
        from models import Marketer  # noqa: PLC0415 - 循環を避け、運用Queryだけで使う

        stmt = (
            select(ApiIdempotencyRequest)
            .join(Marketer, Marketer.id == ApiIdempotencyRequest.marketer_id)
            .where(
                ApiIdempotencyRequest.operation == ApiOperation.PUBLISH_X_POST,
                or_(
                    ApiIdempotencyRequest.status == ApiIdempotencyStatus.OUTCOME_UNKNOWN,
                    and_(
                        ApiIdempotencyRequest.status == ApiIdempotencyStatus.PROCESSING,
                        ApiIdempotencyRequest.lease_expires_at <= now,
                        ApiIdempotencyRequest.external_result.is_not(None),
                    ),
                ),
            )
            .order_by(ApiIdempotencyRequest.updated_at, ApiIdempotencyRequest.id)
            .limit(limit)
        )
        if company_id is not None:
            stmt = stmt.where(Marketer.company_id == company_id)
        return list((await self._session.execute(stmt)).scalars())

    async def reserve(
        self,
        *,
        marketer_id: int,
        session_id: int,
        operation: ApiOperation,
        key: uuid.UUID,
        request_hash: str,
        token: uuid.UUID,
        lease_expires_at: datetime,
        now: datetime,
    ) -> ApiIdempotencyRequest | None:
        """`processing` の行を原子的に作成する。既にあれば None（実行権を得られない）。"""
        stmt = (
            pg_insert(ApiIdempotencyRequest)
            .values(
                marketer_id=marketer_id,
                session_id=session_id,
                operation=operation,
                idempotency_key=key,
                request_hash=request_hash,
                status=ApiIdempotencyStatus.PROCESSING,
                execution_token=token,
                lease_expires_at=lease_expires_at,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(index_elements=["marketer_id", "operation", "idempotency_key"])
            .returning(ApiIdempotencyRequest.id)
        )
        new_id = (await self._session.execute(stmt)).scalar_one_or_none()
        return None if new_id is None else await self.get(new_id)

    async def has_unresolved_duplicate(
        self, marketer_id: int, request_hash: str, *, exclude_id: int
    ) -> bool:
        """別キーで、同じ内容の処理中または結果不明のX投稿があるか（X_POST_UNRESOLVED）。"""
        stmt = select(ApiIdempotencyRequest.id).where(
            ApiIdempotencyRequest.marketer_id == marketer_id,
            ApiIdempotencyRequest.operation == ApiOperation.PUBLISH_X_POST,
            ApiIdempotencyRequest.request_hash == request_hash,
            ApiIdempotencyRequest.id != exclude_id,
            ApiIdempotencyRequest.status.in_(
                [ApiIdempotencyStatus.PROCESSING, ApiIdempotencyStatus.OUTCOME_UNKNOWN]
            ),
        )
        return (await self._session.execute(stmt.limit(1))).first() is not None

    async def attach_turn(self, request_id: int, turn_id: int, now: datetime) -> None:
        """API実行Turnを関連付ける。"""
        await self._session.execute(
            update(ApiIdempotencyRequest)
            .where(ApiIdempotencyRequest.id == request_id)
            .values(agent_turn_id=turn_id, updated_at=now)
        )

    async def reacquire(
        self,
        row: ApiIdempotencyRequest,
        *,
        new_token: uuid.UUID,
        new_lease_expires_at: datetime,
        now: datetime,
    ) -> bool:
        """期限切れの `processing` の実行権を、Compare-and-setで取得し直す。"""
        stmt = (
            update(ApiIdempotencyRequest)
            .where(
                ApiIdempotencyRequest.id == row.id,
                ApiIdempotencyRequest.status == ApiIdempotencyStatus.PROCESSING,
                ApiIdempotencyRequest.execution_token == row.execution_token,
                ApiIdempotencyRequest.lease_expires_at == row.lease_expires_at,
                ApiIdempotencyRequest.lease_expires_at <= now,
            )
            .values(
                execution_token=new_token, lease_expires_at=new_lease_expires_at, updated_at=now
            )
            .returning(ApiIdempotencyRequest.id)
        )
        return (await self._session.execute(stmt)).first() is not None

    def _held(
        self, request_id: int, token: uuid.UUID, now: datetime, *, require_lease: bool
    ) -> Any:  # noqa: ANN401 - SQL式のため
        conditions = [
            ApiIdempotencyRequest.id == request_id,
            ApiIdempotencyRequest.status == ApiIdempotencyStatus.PROCESSING,
            ApiIdempotencyRequest.execution_token == token,
        ]
        if require_lease:
            conditions.append(ApiIdempotencyRequest.lease_expires_at > now)
        return and_(*conditions)

    async def mark_external_started(self, request_id: int, token: uuid.UUID, now: datetime) -> bool:
        """X APIへ送信する直前に、外部作用の開始を記録する。有効なLeaseを条件とする。"""
        stmt = (
            update(ApiIdempotencyRequest)
            .where(self._held(request_id, token, now, require_lease=True))
            .values(external_effect_started_at=now, updated_at=now)
            .returning(ApiIdempotencyRequest.id)
        )
        return (await self._session.execute(stmt)).first() is not None

    async def save_external_result(
        self, request_id: int, token: uuid.UUID, result: dict[str, Any], now: datetime
    ) -> bool:
        """X投稿の成功結果を保存する。有効なLeaseを条件とする。"""
        stmt = (
            update(ApiIdempotencyRequest)
            .where(self._held(request_id, token, now, require_lease=True))
            .values(external_result=result, updated_at=now)
            .returning(ApiIdempotencyRequest.id)
        )
        return (await self._session.execute(stmt)).first() is not None

    async def finalize(
        self,
        request_id: int,
        token: uuid.UUID,
        *,
        status: ApiIdempotencyStatus,
        http_status: int,
        response_body: dict[str, Any],
        now: datetime,
        require_lease: bool = True,
    ) -> bool:
        """Responseを確定する。`processing`・実行Token一致（・有効なLease）を条件とする。"""
        stmt = (
            update(ApiIdempotencyRequest)
            .where(self._held(request_id, token, now, require_lease=require_lease))
            .values(
                status=status,
                http_status=http_status,
                response_body=response_body,
                completed_at=now,
                updated_at=now,
            )
            .returning(ApiIdempotencyRequest.id)
        )
        return (await self._session.execute(stmt)).first() is not None

    async def expire_lease(self, request_id: int, token: uuid.UUID, now: datetime) -> bool:
        """有効なLeaseを即時失効させる。実行権を失っていれば False。"""
        stmt = (
            update(ApiIdempotencyRequest)
            .where(self._held(request_id, token, now, require_lease=True))
            .values(lease_expires_at=now, updated_at=now)
            .returning(ApiIdempotencyRequest.id)
        )
        return (await self._session.execute(stmt)).first() is not None

    async def recover_unknown(
        self,
        row: ApiIdempotencyRequest,
        *,
        http_status: int,
        response_body: dict[str, Any],
        now: datetime,
    ) -> bool:
        """外部作用開始後にLeaseが切れ、`external_result` がない行を `outcome_unknown` へ確定する。

        期限切れと旧Tokenを条件とする専用の復旧遷移で、有効なLeaseは要求しない。
        """
        stmt = (
            update(ApiIdempotencyRequest)
            .where(
                ApiIdempotencyRequest.id == row.id,
                ApiIdempotencyRequest.status == ApiIdempotencyStatus.PROCESSING,
                ApiIdempotencyRequest.operation == ApiOperation.PUBLISH_X_POST,
                ApiIdempotencyRequest.execution_token == row.execution_token,
                ApiIdempotencyRequest.lease_expires_at == row.lease_expires_at,
                ApiIdempotencyRequest.lease_expires_at <= now,
                ApiIdempotencyRequest.external_effect_started_at.is_not(None),
                ApiIdempotencyRequest.external_result.is_(None),
            )
            .values(
                status=ApiIdempotencyStatus.OUTCOME_UNKNOWN,
                http_status=http_status,
                response_body=response_body,
                completed_at=now,
                updated_at=now,
            )
            .returning(ApiIdempotencyRequest.id)
        )
        return (await self._session.execute(stmt)).first() is not None

    async def resolve_unknown(
        self,
        request_id: int,
        *,
        status: ApiIdempotencyStatus,
        http_status: int,
        response_body: dict[str, Any],
        now: datetime,
    ) -> bool:
        """`outcome_unknown`を確定結果へ一度だけCompare-and-setする。"""
        stmt = (
            update(ApiIdempotencyRequest)
            .where(
                ApiIdempotencyRequest.id == request_id,
                ApiIdempotencyRequest.operation == ApiOperation.PUBLISH_X_POST,
                ApiIdempotencyRequest.status == ApiIdempotencyStatus.OUTCOME_UNKNOWN,
            )
            .values(
                status=status,
                http_status=http_status,
                response_body=response_body,
                completed_at=now,
                updated_at=now,
            )
            .returning(ApiIdempotencyRequest.id)
        )
        return (await self._session.execute(stmt)).first() is not None
