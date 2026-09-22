"""Agentのセッション・ターン・アイテムのRepository。"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, exists, func, literal, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from domain.enums import (
    AgentContentSource,
    AgentContextClass,
    AgentItemContextStatus,
    AgentItemType,
    AgentTurnStatus,
    AgentType,
    ToolExecutionStatus,
)
from models import (
    AgentItem,
    AgentSession,
    AgentTurn,
    ApiIdempotencyRequest,
    SecurityEvent,
    ToolExecution,
)


@dataclass(frozen=True)
class TurnBundle:
    """Turnと、その表示に必要な関連データ。"""

    turn: AgentTurn
    items: list[AgentItem]
    notices: list[SecurityEvent]
    is_approval: bool


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
        return (await self._session.execute(stmt)).first() is not None

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
