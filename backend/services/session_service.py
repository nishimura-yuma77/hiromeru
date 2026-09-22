"""Sessionの作成・一覧・履歴・Turn取得（API_DESIGN 5.2、5.4〜5.6）。"""

from datetime import timedelta

from sqlalchemy.exc import SQLAlchemyError

from core.errors import DEFAULT_MESSAGES, AppError
from core.logging import get_logger, safe_error_text
from domain.cursor import encode_cursor
from domain.timefmt import format_utc
from models import AgentSession
from repositories.agent import SessionRepository, TurnRepository
from services.context import AuthContext, ServiceContext
from services.paging import read_cursor, require_datetime, require_int
from services.turn_view import TurnViewLoader, build_turn_view
from services.views import HistoryView, SessionListView, SessionView, TurnView

_log = get_logger(__name__)
_CURSOR_KIND = "sessions"


def to_session_view(session: AgentSession) -> SessionView:
    """Sessionを表示形式へ変換する。"""
    return SessionView(session.id, session.title, session.created_at, session.updated_at)


class SessionService:
    """Sessionと、その履歴の参照。"""

    def __init__(self, ctx: ServiceContext) -> None:
        """サービスの依存を受け取る。"""
        self._ctx = ctx

    async def create(self, auth: AuthContext) -> SessionView:
        """親Sessionを作成する（Turnは作らない）。

        Raises:
            AppError: 保存できない場合（AGENT_SESSION_SAVE_FAILED）。
        """
        try:
            async with self._ctx.session_factory() as session, session.begin():
                created = await SessionRepository(session).create(
                    auth.marketer_id, self._ctx.clock.now()
                )
                return to_session_view(created)
        except SQLAlchemyError as error:
            _log.error("agent_session_save_failed", error=safe_error_text(error))
            raise AppError("AGENT_SESSION_SAVE_FAILED") from None

    async def list(self, auth: AuthContext, *, limit: int, cursor: str | None) -> SessionListView:
        """親Sessionを、最終更新日時の新しい順に返す（5.5）。"""
        after = None
        if cursor is not None:
            values = read_cursor(cursor, _CURSOR_KIND)
            after = (require_datetime(values, "updated_at"), require_int(values, "id"))
        async with self._ctx.session_factory() as session:
            rows = await SessionRepository(session).list_parents(
                auth.marketer_id, limit=limit + 1, after=after
            )
        shown = rows[:limit]
        next_cursor = None
        if len(rows) > limit:
            last = shown[-1]
            next_cursor = encode_cursor(
                _CURSOR_KIND, {"updated_at": format_utc(last.updated_at), "id": last.id}
            )
        return SessionListView([to_session_view(row) for row in shown], next_cursor)

    async def history(
        self,
        auth: AuthContext,
        session_id: int,
        *,
        limit: int,
        before_turn_number: int | None,
    ) -> HistoryView:
        """Sessionの情報とTurnの履歴を返す（5.6）。先に中断されたTurnを復旧する。

        Raises:
            AppError: 親Sessionが存在しない、所有していない場合（AGENT_SESSION_NOT_FOUND）。
        """
        agent_session = await self._require_session(auth, session_id)
        await self.recover_stale_turns(session_id)
        async with self._ctx.session_factory() as session:
            repository = TurnRepository(session)
            turns = await repository.list_turns(
                session_id, limit=limit + 1, before_turn_number=before_turn_number
            )
            has_more = len(turns) > limit
            shown = list(reversed(turns[:limit]))
            bundles = await repository.bundles(shown)
        return HistoryView(
            to_session_view(agent_session),
            [build_turn_view(bundle) for bundle in bundles],
            has_more,
        )

    async def get_turn(self, auth: AuthContext, session_id: int, turn_id: int) -> TurnView:
        """Turnの状態と表示対象のItemを返す（5.4）。先に中断されたTurnを復旧する。

        Raises:
            AppError: Sessionが存在しない（AGENT_SESSION_NOT_FOUND）、Turnが存在しない
                （AGENT_TURN_NOT_FOUND）場合。
        """
        await self._require_session(auth, session_id)
        await self.recover_stale_turns(session_id)
        view = await TurnViewLoader(self._ctx).load(session_id, turn_id)
        if view is None:
            raise AppError("AGENT_TURN_NOT_FOUND")
        return view

    async def _require_session(self, auth: AuthContext, session_id: int) -> AgentSession:
        async with self._ctx.session_factory() as session:
            found = await SessionRepository(session).get_parent(auth.marketer_id, session_id)
        if found is None:
            raise AppError("AGENT_SESSION_NOT_FOUND")
        return found

    async def recover_stale_turns(self, session_id: int) -> None:
        """このSessionの中断されたTurnを `failed`（TURN_INTERRUPTED）へ確定する。冪等。"""
        now = self._ctx.clock.now()
        threshold = now - timedelta(seconds=self._ctx.settings.stale_turn_seconds)
        async with self._ctx.session_factory() as session, session.begin():
            recovered = await TurnRepository(session).recover_stale(
                session_id,
                threshold=threshold,
                now=now,
                message=DEFAULT_MESSAGES["TURN_INTERRUPTED"],
            )
        if recovered:
            _log.warning("turn_interrupted_recovered", session_id=session_id, turn_ids=recovered)
