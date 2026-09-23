"""未訪問Sessionを含む中断Agent Turnの定期復旧。"""

from datetime import timedelta

from core.errors import DEFAULT_MESSAGES
from core.logging import get_logger
from repositories.agent import TurnRepository
from services.context import ServiceContext

_log = get_logger(__name__)


class TurnRecoveryService:
    """全Session横断の冪等なstale Turn復旧を実行する。"""

    def __init__(self, ctx: ServiceContext) -> None:
        """実行依存を保持する。"""
        self._ctx = ctx

    async def recover_all(self) -> list[int]:
        """親・子Sessionのstale Chat Turnを復旧し、Approval Turnは除外する。"""
        now = self._ctx.clock.now()
        threshold = now - timedelta(seconds=self._ctx.settings.stale_turn_seconds)
        async with self._ctx.session_factory() as session, session.begin():
            recovered = await TurnRepository(session).recover_all_stale(
                threshold=threshold,
                now=now,
                message=DEFAULT_MESSAGES["TURN_INTERRUPTED"],
            )
        if recovered:
            _log.warning(
                "turn_interrupted_recovered", count=len(recovered), source="scheduled"
            )
        return recovered
