"""Agentのセッション・ターン・アイテムのRepository。"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, exists, func, literal, or_, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from domain.enums import (
    AgentContentSource,
    AgentContextClass,
    AgentItemContextStatus,
    AgentItemType,
    AgentTurnStatus,
    AgentType,
    SecurityDetector,
    SecurityEnforcement,
    SecurityEventType,
    ToolExecutionStatus,
)
from models import (
    AgentContextCheckpoint,
    AgentContextCheckpointItem,
    AgentItem,
    AgentSession,
    AgentTurn,
    ApiIdempotencyRequest,
    Marketer,
    SecurityEvent,
    ToolExecution,
)


@dataclass(frozen=True)
class ToolRuntimeRecord:
    """DB正本から得たTool実行境界。"""

    agent_type: AgentType
    parent_session_id: int | None
    started_at: datetime
    turn_status: AgentTurnStatus


@dataclass(frozen=True)
class PreparedToolExecution:
    """get-or-createした論理Tool実行。"""

    tool_call: AgentItem
    execution: ToolExecution
    terminal_result: AgentItem | None


@dataclass(frozen=True)
class TurnBundle:
    """Turnと、その表示に必要な関連データ。"""

    turn: AgentTurn
    items: list[AgentItem]
    notices: list[SecurityEvent]
    is_approval: bool


@dataclass(frozen=True)
class CheckpointBundle:
    """有効Checkpointと境界、要約元Item ID。"""

    checkpoint: AgentContextCheckpoint
    through_turn_number: int
    source_item_ids: tuple[int, ...]


class InvalidCheckpointSourcesError(ValueError):
    """Checkpointのsource Itemが許可された親Session・Turn境界に属さない。"""


class ToolCallConflictError(ValueError):
    """同じstable keyが異なるTool Call内容へ再利用された。"""


class SessionRepository:
    """親セッションのDBアクセス。すべてマーケターの条件を含める。"""

    def __init__(self, session: AsyncSession) -> None:
        """セッションを受け取る。"""
        self._session = session

    async def create(self, marketer_id: int, now: datetime) -> AgentSession:
        """親セッションを作成する（title は null）。"""
        agent_session = AgentSession(
            marketer_id=marketer_id,
            agent=AgentType.PARENT,
            created_at=now,
            updated_at=now,
        )
        self._session.add(agent_session)
        await self._session.flush()
        return agent_session

    async def get_parent(
        self, marketer_id: int, session_id: int, *, lock: bool = False
    ) -> AgentSession | None:
        """認証済みマーケターが所有する親セッションを取得する。

        子セッション、他のマーケターのセッション、存在しないIDは None。
        アーカイブ済みも返す（呼び出し側で判定する）。
        """
        stmt = select(AgentSession).where(
            AgentSession.id == session_id,
            AgentSession.marketer_id == marketer_id,
            AgentSession.agent == AgentType.PARENT,
            AgentSession.parent_session_id.is_(None),
        )
        if lock:
            stmt = stmt.with_for_update()
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def touch(self, session_id: int, now: datetime, title: str | None = None) -> None:
        """`updated_at` を更新する。`title` が渡され、かつ未設定の場合だけ設定する。"""
        values: dict[str, Any] = {"updated_at": now}
        if title is not None:
            values["title"] = func.coalesce(AgentSession.title, title)
        await self._session.execute(
            update(AgentSession).where(AgentSession.id == session_id).values(**values)
        )

    async def list_parents(
        self, marketer_id: int, *, limit: int, after: tuple[datetime, int] | None
    ) -> list[AgentSession]:
        """`updated_at` の降順（同じ場合は id の降順）で、未アーカイブの親セッションを返す。"""
        stmt = select(AgentSession).where(
            AgentSession.marketer_id == marketer_id,
            AgentSession.agent == AgentType.PARENT,
            AgentSession.parent_session_id.is_(None),
            AgentSession.archived_at.is_(None),
        )
        if after is not None:
            stmt = stmt.where(
                tuple_(AgentSession.updated_at, AgentSession.id)
                < tuple_(
                    literal(after[0], AgentSession.updated_at.type),
                    literal(after[1], AgentSession.id.type),
                )
            )
        stmt = stmt.order_by(AgentSession.updated_at.desc(), AgentSession.id.desc()).limit(limit)
        return list((await self._session.execute(stmt)).scalars())


class TurnRepository:
    """ターン・アイテム・セキュリティ通知のDBアクセス。"""

    def __init__(self, session: AsyncSession) -> None:
        """セッションを受け取る。"""
        self._session = session

    @staticmethod
    def _is_api_turn(turn_id_column: Any) -> Any:  # noqa: ANN401 - SQL式のため
        """API実行Turn（冪等性レコードから参照されるTurn）か。"""
        return exists().where(ApiIdempotencyRequest.agent_turn_id == turn_id_column)

    async def recover_stale(
        self, session_id: int, *, threshold: datetime, now: datetime, message: str
    ) -> list[int]:
        """中断されたTurnを `failed`（TURN_INTERRUPTED）へ確定する。

        AGENT_DESIGN「中断されたTurnの復旧」に従う。

        対象は、pending・running のまま復旧判定時間を超えた、API実行Turnではない Turn。
        `status` を条件とする条件付きUPDATEのため、何度呼んでも結果は変わらない。
        """
        stmt = (
            update(AgentTurn)
            .where(
                AgentTurn.session_id == session_id,
                AgentTurn.status.in_([AgentTurnStatus.PENDING, AgentTurnStatus.RUNNING]),
                func.coalesce(AgentTurn.started_at, AgentTurn.created_at) < threshold,
                ~self._is_api_turn(AgentTurn.id),
            )
            .values(
                status=AgentTurnStatus.FAILED,
                error_code="TURN_INTERRUPTED",
                error_message=message,
                completed_at=now,
                updated_at=now,
            )
            .returning(AgentTurn.id)
        )
        recovered = list((await self._session.execute(stmt)).scalars())
        if recovered:
            cancel = (
                update(ToolExecution)
                .where(
                    ToolExecution.status.in_(
                        [ToolExecutionStatus.PENDING, ToolExecutionStatus.RUNNING]
                    ),
                    ToolExecution.tool_call_item_id.in_(
                        select(AgentItem.id).where(AgentItem.agent_turn_id.in_(recovered))
                    ),
                )
                .values(status=ToolExecutionStatus.CANCELLED, completed_at=now)
            )
            await self._session.execute(cancel)
        return recovered

    async def has_active_chat_turn(self, session_id: int) -> bool:
        """pending・running のAgent Turn（API実行Turnを除く）があるか。"""
        stmt = select(
            exists().where(
                AgentTurn.session_id == session_id,
                AgentTurn.status.in_([AgentTurnStatus.PENDING, AgentTurnStatus.RUNNING]),
                ~self._is_api_turn(AgentTurn.id),
            )
        )
        return bool((await self._session.execute(stmt)).scalar())

    async def create_turn(self, session_id: int, now: datetime) -> AgentTurn:
        """Turnを `running` で作成する。Session行をロックした状態で呼ぶこと。"""
        max_number = (
            await self._session.execute(
                select(func.coalesce(func.max(AgentTurn.turn_number), 0)).where(
                    AgentTurn.session_id == session_id
                )
            )
        ).scalar_one()
        turn = AgentTurn(
            session_id=session_id,
            turn_number=max_number + 1,
            status=AgentTurnStatus.RUNNING,
            started_at=now,
            created_at=now,
            updated_at=now,
        )
        self._session.add(turn)
        await self._session.flush()
        return turn

    async def append_item(
        self,
        turn_id: int,
        *,
        key: str,
        item_type: AgentItemType,
        source: AgentContentSource,
        content: dict[str, Any],
        now: datetime,
        context_class: AgentContextClass = AgentContextClass.CONVERSATION,
    ) -> AgentItem:
        """アイテムを追記する。同じ `key` が保存済みなら、それを返す（二重保存を防ぐ）。"""
        existing = (
            await self._session.execute(
                select(AgentItem).where(
                    AgentItem.agent_turn_id == turn_id, AgentItem.idempotency_key == key
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        # ターン行を更新して原子的に採番する。
        number = (
            await self._session.execute(
                update(AgentTurn)
                .where(AgentTurn.id == turn_id)
                .values(next_item_number=AgentTurn.next_item_number + 1)
                .returning(AgentTurn.next_item_number - 1)
            )
        ).scalar_one()
        item = AgentItem(
            agent_turn_id=turn_id,
            item_number=number,
            idempotency_key=key,
            item_type=item_type,
            context_class=context_class,
            content_source=source,
            context_status=AgentItemContextStatus.ACTIVE,
            content=content,
            created_at=now,
        )
        self._session.add(item)
        await self._session.flush()
        return item

    async def append_item_if_running(
        self,
        turn_id: int,
        *,
        key: str,
        item_type: AgentItemType,
        source: AgentContentSource,
        content: dict[str, Any],
        now: datetime,
        context_class: AgentContextClass = AgentContextClass.CONVERSATION,
    ) -> AgentItem | None:
        """Turnがrunningの場合だけItemを追記する。終端化との競合では何も書かない。"""
        existing = (
            await self._session.execute(
                select(AgentItem)
                .join(AgentTurn, AgentTurn.id == AgentItem.agent_turn_id)
                .where(
                    AgentItem.agent_turn_id == turn_id,
                    AgentItem.idempotency_key == key,
                    AgentTurn.status == AgentTurnStatus.RUNNING,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        number = (
            await self._session.execute(
                update(AgentTurn)
                .where(
                    AgentTurn.id == turn_id,
                    AgentTurn.status == AgentTurnStatus.RUNNING,
                )
                .values(next_item_number=AgentTurn.next_item_number + 1)
                .returning(AgentTurn.next_item_number - 1)
            )
        ).scalar_one_or_none()
        if number is None:
            return None
        item = AgentItem(
            agent_turn_id=turn_id,
            item_number=number,
            idempotency_key=key,
            item_type=item_type,
            context_class=context_class,
            content_source=source,
            context_status=AgentItemContextStatus.ACTIVE,
            content=content,
            created_at=now,
        )
        self._session.add(item)
        await self._session.flush()
        return item

    async def latest_checkpoint(
        self, session_id: int, *, before_turn_number: int
    ) -> CheckpointBundle | None:
        """現在Turnより前にある最新の有効Checkpointを返す。"""
        row = (
            await self._session.execute(
                select(AgentContextCheckpoint, AgentTurn.turn_number)
                .join(AgentTurn, AgentTurn.id == AgentContextCheckpoint.compacted_through_turn_id)
                .where(
                    AgentContextCheckpoint.session_id == session_id,
                    AgentContextCheckpoint.invalidated_at.is_(None),
                    AgentTurn.turn_number < before_turn_number,
                )
                .order_by(
                    AgentContextCheckpoint.created_at.desc(),
                    AgentContextCheckpoint.id.desc(),
                )
                .limit(1)
            )
        ).one_or_none()
        if row is None:
            return None
        checkpoint, turn_number = row
        source_ids = tuple(
            (
                await self._session.execute(
                    select(AgentContextCheckpointItem.item_id)
                    .where(AgentContextCheckpointItem.checkpoint_id == checkpoint.id)
                    .order_by(AgentContextCheckpointItem.item_id)
                )
            ).scalars()
        )
        return CheckpointBundle(checkpoint, turn_number, source_ids)

    async def completed_context_items(
        self,
        session_id: int,
        *,
        after_turn_number: int = 0,
        before_turn_number: int,
    ) -> list[tuple[AgentTurn, AgentItem]]:
        """Checkpoint境界と現在Turnの間にある完了Itemを会話順で返す。"""
        stmt = (
            select(AgentTurn, AgentItem)
            .join(AgentItem, AgentItem.agent_turn_id == AgentTurn.id)
            .where(
                AgentTurn.session_id == session_id,
                AgentTurn.status == AgentTurnStatus.COMPLETED,
                AgentTurn.turn_number > after_turn_number,
                AgentTurn.turn_number < before_turn_number,
            )
            .order_by(AgentTurn.turn_number, AgentItem.item_number)
        )
        return list((await self._session.execute(stmt)).tuples())

    async def current_user_item(self, turn_id: int) -> AgentItem | None:
        """現在のrunning Turnのuser inputを1件取得する。"""
        stmt = (
            select(AgentItem)
            .join(AgentTurn, AgentTurn.id == AgentItem.agent_turn_id)
            .where(
                AgentTurn.id == turn_id,
                AgentTurn.status == AgentTurnStatus.RUNNING,
                AgentItem.item_type == AgentItemType.USER_MESSAGE,
            )
            .order_by(AgentItem.item_number)
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def recent_security_events(
        self, session_id: int, *, before_turn_number: int, turn_limit: int = 5
    ) -> list[SecurityEvent]:
        """現在Turnより前の直近Turnに属するSecurity Eventを返す。"""
        recent_turns = (
            select(AgentTurn.id)
            .where(
                AgentTurn.session_id == session_id,
                AgentTurn.turn_number < before_turn_number,
            )
            .order_by(AgentTurn.turn_number.desc())
            .limit(turn_limit)
            .subquery()
        )
        stmt = (
            select(SecurityEvent)
            .join(AgentTurn, AgentTurn.id == SecurityEvent.agent_turn_id)
            .where(SecurityEvent.agent_turn_id.in_(select(recent_turns.c.id)))
            .order_by(AgentTurn.turn_number, SecurityEvent.detected_at, SecurityEvent.id)
        )
        return list((await self._session.execute(stmt)).scalars())

    async def create_checkpoint(
        self,
        session_id: int,
        through_turn_id: int,
        *,
        summary: str,
        source_item_ids: tuple[int, ...],
        now: datetime,
    ) -> AgentContextCheckpoint:
        """source境界を検証し、Checkpointと中間行を同じTransactionへ追加する。"""
        boundary_number = (
            await self._session.execute(
                select(AgentTurn.turn_number)
                .join(AgentSession, AgentSession.id == AgentTurn.session_id)
                .where(
                    AgentTurn.id == through_turn_id,
                    AgentTurn.session_id == session_id,
                    AgentTurn.status == AgentTurnStatus.COMPLETED,
                    AgentSession.agent == AgentType.PARENT,
                    AgentSession.parent_session_id.is_(None),
                )
            )
        ).scalar_one_or_none()
        unique_ids = tuple(dict.fromkeys(source_item_ids))
        if boundary_number is None or not unique_ids:
            raise InvalidCheckpointSourcesError
        valid_count = (
            await self._session.execute(
                select(func.count(AgentItem.id))
                .join(AgentTurn, AgentTurn.id == AgentItem.agent_turn_id)
                .join(AgentSession, AgentSession.id == AgentTurn.session_id)
                .where(
                    AgentItem.id.in_(unique_ids),
                    AgentTurn.session_id == session_id,
                    AgentTurn.status == AgentTurnStatus.COMPLETED,
                    AgentTurn.turn_number <= boundary_number,
                    AgentSession.agent == AgentType.PARENT,
                    AgentSession.parent_session_id.is_(None),
                )
            )
        ).scalar_one()
        if valid_count != len(unique_ids):
            raise InvalidCheckpointSourcesError
        checkpoint = AgentContextCheckpoint(
            session_id=session_id,
            compacted_through_turn_id=through_turn_id,
            summary=summary,
            created_at=now,
        )
        self._session.add(checkpoint)
        await self._session.flush()
        self._session.add_all(
            AgentContextCheckpointItem(checkpoint_id=checkpoint.id, item_id=item_id)
            for item_id in unique_ids
        )
        await self._session.flush()
        return checkpoint

    async def quarantine_item(
        self,
        item_id: int,
        *,
        reason: str,
        context_override: dict[str, Any],
        now: datetime,
    ) -> bool:
        """Itemを隔離し、そのItemをsourceに持つ有効Checkpointを同時に無効化する。"""
        quarantined = (
            await self._session.execute(
                update(AgentItem)
                .where(
                    AgentItem.id == item_id,
                    AgentItem.context_status == AgentItemContextStatus.ACTIVE,
                )
                .values(
                    context_status=AgentItemContextStatus.QUARANTINED,
                    quarantine_reason=reason,
                    context_override=context_override,
                    quarantined_at=now,
                )
                .returning(AgentItem.id)
            )
        ).scalar_one_or_none()
        if quarantined is None:
            return False
        checkpoint_ids = select(AgentContextCheckpointItem.checkpoint_id).where(
            AgentContextCheckpointItem.item_id == item_id
        )
        await self._session.execute(
            update(AgentContextCheckpoint)
            .where(
                AgentContextCheckpoint.id.in_(checkpoint_ids),
                AgentContextCheckpoint.invalidated_at.is_(None),
            )
            .values(invalidated_at=now, invalidation_reason=reason)
        )
        return True

    async def finish_turn(
        self,
        turn_id: int,
        *,
        status: AgentTurnStatus,
        now: datetime,
        error_code: str | None = None,
        error_message: str | None = None,
        only_running: bool = True,
    ) -> bool:
        """Turnを終端状態へ更新する。`status = running` を条件とし、更新できなければ False。

        終端状態になったTurnへは書き込まない（DB.dbml）。
        """
        conditions = [AgentTurn.id == turn_id]
        if only_running:
            conditions.append(AgentTurn.status == AgentTurnStatus.RUNNING)
        stmt = (
            update(AgentTurn)
            .where(and_(*conditions))
            .values(
                status=status,
                error_code=error_code,
                error_message=error_message,
                completed_at=now,
                updated_at=now,
            )
            .returning(AgentTurn.id)
        )
        finished = (await self._session.execute(stmt)).first() is not None
        if finished:
            await self._session.execute(
                update(ToolExecution)
                .where(
                    ToolExecution.status.in_(
                        [ToolExecutionStatus.PENDING, ToolExecutionStatus.RUNNING]
                    ),
                    ToolExecution.tool_call_item_id.in_(
                        select(AgentItem.id).where(AgentItem.agent_turn_id == turn_id)
                    ),
                )
                .values(status=ToolExecutionStatus.CANCELLED, completed_at=now)
            )
        return finished

    async def get_turn(self, session_id: int, turn_id: int) -> AgentTurn | None:
        """指定セッションのTurnを取得する。"""
        stmt = select(AgentTurn).where(AgentTurn.id == turn_id, AgentTurn.session_id == session_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_turns(
        self, session_id: int, *, limit: int, before_turn_number: int | None
    ) -> list[AgentTurn]:
        """`turn_number` の降順でTurnを返す。"""
        stmt = select(AgentTurn).where(AgentTurn.session_id == session_id)
        if before_turn_number is not None:
            stmt = stmt.where(AgentTurn.turn_number < before_turn_number)
        stmt = stmt.order_by(AgentTurn.turn_number.desc()).limit(limit)
        return list((await self._session.execute(stmt)).scalars())

    async def bundles(self, turns: list[AgentTurn]) -> list[TurnBundle]:
        """Turnの表示に必要なアイテム・通知・種別を、まとめて取得する。"""
        ids = [turn.id for turn in turns]
        if not ids:
            return []
        items: dict[int, list[AgentItem]] = {turn_id: [] for turn_id in ids}
        item_stmt = (
            select(AgentItem)
            .where(
                AgentItem.agent_turn_id.in_(ids),
                AgentItem.context_status == AgentItemContextStatus.ACTIVE,
            )
            .order_by(AgentItem.agent_turn_id, AgentItem.item_number)
        )
        for item in (await self._session.execute(item_stmt)).scalars():
            items[item.agent_turn_id].append(item)
        notices: dict[int, list[SecurityEvent]] = {turn_id: [] for turn_id in ids}
        event_stmt = (
            select(SecurityEvent)
            .where(SecurityEvent.agent_turn_id.in_(ids))
            .order_by(SecurityEvent.detected_at, SecurityEvent.id)
        )
        for event in (await self._session.execute(event_stmt)).scalars():
            notices[event.agent_turn_id].append(event)
        approval_ids = set(
            (
                await self._session.execute(
                    select(ApiIdempotencyRequest.agent_turn_id).where(
                        ApiIdempotencyRequest.agent_turn_id.in_(ids)
                    )
                )
            ).scalars()
        )
        return [
            TurnBundle(turn, items[turn.id], notices[turn.id], turn.id in approval_ids)
            for turn in turns
        ]


class ToolExecutionRepository:
    """Tool実行の短いTransaction用DBアクセス。"""

    def __init__(self, session: AsyncSession) -> None:
        """DB sessionを受け取る。"""
        self._session = session

    @staticmethod
    def _require_matching_call(
        tool_call: AgentItem, *, name: str, arguments: dict[str, Any]
    ) -> None:
        expected = {
            "name": name,
            "call_key": tool_call.idempotency_key.removeprefix("tool:"),
            "arguments": arguments,
        }
        if tool_call.content != expected:
            raise ToolCallConflictError

    async def runtime_record(
        self, *, marketer_id: int, company_id: int, session_id: int, turn_id: int
    ) -> ToolRuntimeRecord | None:
        """Tenant、Session、Turn境界をDB正本で検証する。"""
        row = (
            await self._session.execute(
                select(
                    AgentSession.agent,
                    AgentSession.parent_session_id,
                    AgentTurn.started_at,
                    AgentTurn.status,
                )
                .join(AgentTurn, AgentTurn.session_id == AgentSession.id)
                .join(Marketer, Marketer.id == AgentSession.marketer_id)
                .where(
                    AgentSession.id == session_id,
                    AgentSession.marketer_id == marketer_id,
                    Marketer.company_id == company_id,
                    AgentTurn.id == turn_id,
                    AgentTurn.session_id == session_id,
                    or_(
                        and_(
                            AgentSession.agent == AgentType.PARENT,
                            AgentSession.parent_session_id.is_(None),
                        ),
                        and_(
                            AgentSession.agent != AgentType.PARENT,
                            AgentSession.parent_session_id.is_not(None),
                        ),
                    ),
                )
            )
        ).one_or_none()
        if row is None or row.started_at is None:
            return None
        return ToolRuntimeRecord(row.agent, row.parent_session_id, row.started_at, row.status)

    async def prepare(
        self,
        *,
        turn_id: int,
        stable_key: str,
        name: str,
        arguments: dict[str, Any],
        now: datetime,
    ) -> PreparedToolExecution | None:
        """Running Turnだけにtool_callとpending executionをget-or-createする。"""
        turn = (
            await self._session.execute(
                select(AgentTurn)
                .where(AgentTurn.id == turn_id, AgentTurn.status == AgentTurnStatus.RUNNING)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if turn is None:
            return None
        key = f"tool:{stable_key}"
        tool_call = (
            await self._session.execute(
                select(AgentItem).where(
                    AgentItem.agent_turn_id == turn_id,
                    AgentItem.idempotency_key == key,
                )
            )
        ).scalar_one_or_none()
        if tool_call is None:
            tool_call = AgentItem(
                agent_turn_id=turn_id,
                item_number=turn.next_item_number,
                idempotency_key=key,
                item_type=AgentItemType.TOOL_CALL,
                context_class=AgentContextClass.CONVERSATION,
                content_source=AgentContentSource.AGENT_OUTPUT,
                context_status=AgentItemContextStatus.ACTIVE,
                content={"name": name, "call_key": stable_key, "arguments": arguments},
                created_at=now,
            )
            turn.next_item_number += 1
            self._session.add(tool_call)
            await self._session.flush()
        elif tool_call.item_type != AgentItemType.TOOL_CALL:
            return None
        else:
            self._require_matching_call(tool_call, name=name, arguments=arguments)
        execution = (
            await self._session.execute(
                select(ToolExecution).where(ToolExecution.tool_call_item_id == tool_call.id)
            )
        ).scalar_one_or_none()
        if execution is None:
            execution = ToolExecution(
                tool_call_item_id=tool_call.id,
                status=ToolExecutionStatus.PENDING,
                attempt_count=0,
                created_at=now,
            )
            self._session.add(execution)
            await self._session.flush()
        result = (
            await self._session.execute(
                select(AgentItem).where(
                    AgentItem.agent_turn_id == turn_id,
                    AgentItem.related_tool_call_item_id == tool_call.id,
                    AgentItem.item_type == AgentItemType.TOOL_RESULT,
                )
            )
        ).scalar_one_or_none()
        return PreparedToolExecution(tool_call, execution, result)

    async def claim(self, execution_id: int, turn_id: int) -> bool:
        """pending実行を1つの呼出元だけが実行できるようclaimする。"""
        claimed = (
            await self._session.execute(
                update(ToolExecution)
                .where(
                    ToolExecution.id == execution_id,
                    ToolExecution.status == ToolExecutionStatus.PENDING,
                    ToolExecution.tool_call_item_id.in_(
                        select(AgentItem.id).where(AgentItem.agent_turn_id == turn_id)
                    ),
                    exists().where(
                        AgentTurn.id == turn_id,
                        AgentTurn.status == AgentTurnStatus.RUNNING,
                    ),
                )
                .values(status=ToolExecutionStatus.RUNNING)
                .returning(ToolExecution.id)
            )
        ).scalar_one_or_none()
        return claimed is not None

    async def increment_attempt(self, execution_id: int, turn_id: int) -> bool:
        """Running Turnのphysical attempt直前に試行回数を増やす。"""
        updated = (
            await self._session.execute(
                update(ToolExecution)
                .where(
                    ToolExecution.id == execution_id,
                    ToolExecution.status == ToolExecutionStatus.RUNNING,
                    exists().where(
                        AgentTurn.id == turn_id,
                        AgentTurn.status == AgentTurnStatus.RUNNING,
                    ),
                )
                .values(attempt_count=ToolExecution.attempt_count + 1)
                .returning(ToolExecution.id)
            )
        ).scalar_one_or_none()
        return updated is not None

    async def terminal_result(self, turn_id: int, tool_call_item_id: int) -> AgentItem | None:
        """保存済みterminal resultを返す。"""
        return (
            await self._session.execute(
                select(AgentItem).where(
                    AgentItem.agent_turn_id == turn_id,
                    AgentItem.related_tool_call_item_id == tool_call_item_id,
                    AgentItem.item_type == AgentItemType.TOOL_RESULT,
                )
            )
        ).scalar_one_or_none()

    async def terminal_result_by_key(
        self,
        turn_id: int,
        stable_key: str,
        *,
        name: str,
        arguments: dict[str, Any],
    ) -> AgentItem | None:
        """論理Call keyに対応する保存済みterminal resultを返す。"""
        tool_call = (
            await self._session.execute(
                select(AgentItem).where(
                    AgentItem.agent_turn_id == turn_id,
                    AgentItem.idempotency_key == f"tool:{stable_key}",
                    AgentItem.item_type == AgentItemType.TOOL_CALL,
                )
            )
        ).scalar_one_or_none()
        if tool_call is None:
            return None
        self._require_matching_call(tool_call, name=name, arguments=arguments)
        return await self.terminal_result(turn_id, tool_call.id)

    async def finish(
        self,
        *,
        turn_id: int,
        tool_call_item_id: int,
        execution_id: int,
        result: dict[str, Any],
        status: ToolExecutionStatus,
        source: AgentContentSource,
        context_class: AgentContextClass,
        now: datetime,
        event_type: SecurityEventType | None = None,
        detector: SecurityDetector | None = None,
    ) -> AgentItem | None:
        """running条件でresult、block event、execution終端化を原子的に追加する。"""
        turn = (
            await self._session.execute(
                select(AgentTurn)
                .where(AgentTurn.id == turn_id, AgentTurn.status == AgentTurnStatus.RUNNING)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if turn is None:
            return None
        existing = await self.terminal_result(turn_id, tool_call_item_id)
        if existing is not None:
            return existing
        tool_call_type = (
            await self._session.execute(
                select(AgentItem.item_type).where(
                    AgentItem.id == tool_call_item_id,
                    AgentItem.agent_turn_id == turn_id,
                )
            )
        ).scalar_one_or_none()
        if tool_call_type != AgentItemType.TOOL_CALL:
            return None
        execution_status = (
            await self._session.execute(
                select(ToolExecution.status).where(
                    ToolExecution.id == execution_id,
                    ToolExecution.tool_call_item_id == tool_call_item_id,
                    ToolExecution.status.in_(
                        [ToolExecutionStatus.PENDING, ToolExecutionStatus.RUNNING]
                    ),
                ).with_for_update()
            )
        ).scalar_one_or_none()
        if execution_status is None:
            return None
        item = AgentItem(
            agent_turn_id=turn_id,
            related_tool_call_item_id=tool_call_item_id,
            item_number=turn.next_item_number,
            idempotency_key=f"tool-result:{tool_call_item_id}",
            item_type=AgentItemType.TOOL_RESULT,
            context_class=context_class,
            content_source=source,
            context_status=AgentItemContextStatus.ACTIVE,
            content=result,
            created_at=now,
        )
        turn.next_item_number += 1
        self._session.add(item)
        await self._session.flush()
        if event_type is not None and detector is not None:
            self._session.add(
                SecurityEvent(
                    agent_turn_id=turn_id,
                    agent_item_id=item.id,
                    event_type=event_type,
                    detector=detector,
                    source=AgentContentSource.SYSTEM,
                    enforcement=SecurityEnforcement.BLOCKED,
                    summary="Tool execution was blocked by a security control.",
                    event_metadata={},
                    detected_at=now,
                )
            )
        execution_updated = (
            await self._session.execute(
                update(ToolExecution)
                .where(
                    ToolExecution.id == execution_id,
                    ToolExecution.tool_call_item_id == tool_call_item_id,
                    ToolExecution.status.in_(
                        [ToolExecutionStatus.PENDING, ToolExecutionStatus.RUNNING]
                    ),
                )
                .values(status=status, completed_at=now)
                .returning(ToolExecution.id)
            )
        ).scalar_one_or_none()
        if execution_updated is None:
            return None
        await self._session.flush()
        return item
