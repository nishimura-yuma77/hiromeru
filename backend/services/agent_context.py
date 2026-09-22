"""完了Turn、Checkpoint、Security EventからAgent Contextを再構築する。"""

import json
from dataclasses import asdict

from sqlalchemy import select

from agent_runtime.runner import AgentContext, AgentContextEntry, ContextRole
from domain.enums import AgentItemContextStatus, AgentItemType, AgentTurnStatus, AgentType
from models import AgentItem, AgentSession, AgentTurn, SecurityEvent
from repositories.agent import CheckpointBundle, TurnRepository
from services.context import ServiceContext


class ContextCompactionError(Exception):
    """圧縮後もContextのhard limitを満たせない。"""


def estimate_context_utf8_bytes(entries: tuple[AgentContextEntry, ...]) -> int:
    """Context DTOを正規化JSONにした場合のUTF-8 byte数を返す。"""
    serialized = json.dumps(
        [asdict(entry) for entry in entries],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return len(serialized.encode("utf-8"))


def _item_entry(turn_id: int, item: AgentItem) -> AgentContextEntry:
    content = (
        item.context_override
        if item.context_status == AgentItemContextStatus.QUARANTINED
        else item.content
    )
    # DB制約により隔離済みItemのoverrideは必須。
    assert content is not None  # noqa: S101
    roles: dict[AgentItemType, ContextRole] = {
        AgentItemType.USER_MESSAGE: "user",
        AgentItemType.ASSISTANT_MESSAGE: "assistant",
        AgentItemType.TOOL_CALL: "assistant",
        AgentItemType.TOOL_RESULT: "tool",
    }
    return AgentContextEntry(
        kind="item",
        role=roles[item.item_type],
        content=content,
        turn_id=turn_id,
        item_id=item.id,
        item_type=item.item_type.value,
        context_class=item.context_class.value,
        content_source=item.content_source.value,
    )


def _checkpoint_entry(checkpoint: CheckpointBundle) -> AgentContextEntry:
    return AgentContextEntry(
        kind="checkpoint",
        role="system",
        content={"summary": checkpoint.checkpoint.summary},
        turn_id=checkpoint.checkpoint.compacted_through_turn_id,
    )


def _summary_entry(summary: str, through_turn_id: int) -> AgentContextEntry:
    """未保存の要約を、圧縮後Contextの事前検証に使う。"""
    return AgentContextEntry(
        kind="checkpoint",
        role="system",
        content={"summary": summary},
        turn_id=through_turn_id,
    )


class AgentContextBuilder:
    """現在Turn用のContextを構築し、必要な場合だけ古い完了Turnを圧縮する。"""

    def __init__(self, ctx: ServiceContext) -> None:
        """依存を受け取る。"""
        self._ctx = ctx

    async def build(self, session_id: int, turn_id: int) -> AgentContext:
        """Runnerへ渡すContextを構築する。"""
        async with self._ctx.session_factory() as session:
            repository = TurnRepository(session)
            agent_session = (
                await session.execute(select(AgentSession).where(AgentSession.id == session_id))
            ).scalar_one()
            current_turn = await repository.get_turn(session_id, turn_id)
            if current_turn is None or current_turn.status != AgentTurnStatus.RUNNING:
                raise RuntimeError("running Turnが見つかりません")
            checkpoint = await repository.latest_checkpoint(
                session_id, before_turn_number=current_turn.turn_number
            )
            after = checkpoint.through_turn_number if checkpoint is not None else 0
            rows = await repository.completed_context_items(
                session_id,
                after_turn_number=after,
                before_turn_number=current_turn.turn_number,
            )
            current = await repository.current_user_item(turn_id)
            notices = await repository.recent_security_events(
                session_id, before_turn_number=current_turn.turn_number
            )

        if current is None:
            raise RuntimeError("running Turnのuser inputが見つかりません")
        entries = self._entries(checkpoint, rows, current, notices)
        estimate = estimate_context_utf8_bytes(entries)
        threshold = self._ctx.settings.agent_context_compaction_threshold_bytes
        hard_limit = self._ctx.settings.agent_context_hard_limit_bytes
        if estimate <= threshold or agent_session.agent != AgentType.PARENT:
            if estimate > hard_limit:
                raise ContextCompactionError
            return AgentContext(entries, estimate)

        compactable = self._compactable_rows(rows)
        if not compactable:
            if estimate > hard_limit:
                raise ContextCompactionError
            return AgentContext(entries, estimate)

        compact_entries = tuple(
            ([_checkpoint_entry(checkpoint)] if checkpoint is not None else [])
            + [_item_entry(turn.id, item) for turn, item in compactable]
        )
        try:
            summary = await self._ctx.context_compactor.compact(compact_entries)
            boundary = max((turn for turn, _item in compactable), key=lambda turn: turn.turn_number)
            recent_rows = [row for row in rows if row[0].turn_number > boundary.turn_number]
            candidate = self._entries_from_summary(
                summary, boundary.id, recent_rows, current, notices
            )
            candidate_estimate = estimate_context_utf8_bytes(candidate)
            if candidate_estimate > hard_limit:
                raise ContextCompactionError
            new_checkpoint = await self._save_checkpoint(
                session_id, checkpoint, compactable, summary
            )
        except Exception as error:
            if estimate > hard_limit:
                raise ContextCompactionError from error
            return AgentContext(entries, estimate)

        rebuilt = self._entries(new_checkpoint, recent_rows, current, notices)
        rebuilt_estimate = estimate_context_utf8_bytes(rebuilt)
        assert rebuilt_estimate == candidate_estimate  # noqa: S101
        return AgentContext(rebuilt, rebuilt_estimate)

    @staticmethod
    def _entries(
        checkpoint: CheckpointBundle | None,
        rows: list[tuple[AgentTurn, AgentItem]],
        current: AgentItem,
        notices: list[SecurityEvent],
    ) -> tuple[AgentContextEntry, ...]:
        entries: list[AgentContextEntry] = []
        for notice in notices:
            entries.append(
                AgentContextEntry(
                    kind="security_notice",
                    role="system",
                    content={
                        "event_type": notice.event_type.value,
                        "enforcement": notice.enforcement.value,
                    },
                )
            )
        if checkpoint is not None:
            entries.append(_checkpoint_entry(checkpoint))
        entries.extend(_item_entry(turn.id, item) for turn, item in rows)
        entries.append(_item_entry(current.agent_turn_id, current))
        return tuple(entries)

    @staticmethod
    def _entries_from_summary(
        summary: str,
        through_turn_id: int,
        rows: list[tuple[AgentTurn, AgentItem]],
        current: AgentItem,
        notices: list[SecurityEvent],
    ) -> tuple[AgentContextEntry, ...]:
        entries = AgentContextBuilder._entries(None, rows, current, notices)
        notice_count = sum(entry.kind == "security_notice" for entry in entries)
        return (
            *entries[:notice_count],
            _summary_entry(summary, through_turn_id),
            *entries[notice_count:],
        )

    @staticmethod
    def _compactable_rows(
        rows: list[tuple[AgentTurn, AgentItem]],
    ) -> list[tuple[AgentTurn, AgentItem]]:
        """最新completed Turnを必ず除いた、Turn境界単位の圧縮対象を返す。"""
        if not rows:
            return []
        latest_number = max(turn.turn_number for turn, _item in rows)
        return [row for row in rows if row[0].turn_number < latest_number]

    async def _save_checkpoint(
        self,
        session_id: int,
        previous: CheckpointBundle | None,
        rows: list[tuple[AgentTurn, AgentItem]],
        summary: str,
    ) -> CheckpointBundle:
        previous_ids = () if previous is None else previous.source_item_ids
        source_ids = tuple(dict.fromkeys((*previous_ids, *(item.id for _, item in rows))))
        boundary = max((turn for turn, _item in rows), key=lambda turn: turn.turn_number)
        async with self._ctx.session_factory() as session, session.begin():
            repository = TurnRepository(session)
            checkpoint = await repository.create_checkpoint(
                session_id,
                boundary.id,
                summary=summary,
                source_item_ids=source_ids,
                now=self._ctx.clock.now(),
            )
        return CheckpointBundle(checkpoint, boundary.turn_number, source_ids)
