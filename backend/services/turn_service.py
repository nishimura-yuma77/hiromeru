"""メッセージ送信（Agent Turnの開始と実行。API_DESIGN 5.3）。

Agentの本体は `AgentRunner` として差し替える。フェーズ1は固定応答のスタブ。
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta

from agent_runtime.executor import ToolExecutor
from agent_runtime.runner import AgentRunError, AgentRunInput, ProgressReporter
from core.errors import DEFAULT_MESSAGES, ERROR_SPECS, AppError, FieldError
from core.logging import get_logger, safe_error_text
from core.masking import mask_text
from domain.constants import SESSION_TITLE_LENGTH
from domain.enums import AgentContentSource, AgentItemType, AgentTurnStatus
from domain.requests import MessageRequest
from repositories.agent import SessionRepository, TurnRepository
from services.agent_context import AgentContextBuilder, ContextCompactionError
from services.context import AuthContext, ServiceContext
from services.turn_view import TurnViewLoader
from services.validation import BodyLoader, parse_json_object, validate_model
from services.views import TurnView

_log = get_logger(__name__)


@dataclass(frozen=True)
class PreparedTurn:
    """作成済みのTurn。Agentの実行はこの後に行う。"""

    auth: AuthContext
    session_id: int
    turn_id: int
    turn_number: int
    started_at: datetime
    message: str


class TurnService:
    """Turnの作成（短いTransaction）と、Agentの実行・終端状態への更新。"""

    def __init__(self, ctx: ServiceContext) -> None:
        """サービスの依存を受け取る。"""
        self._ctx = ctx

    async def begin(
        self, auth: AuthContext, session_id: int, body_loader: BodyLoader
    ) -> PreparedTurn:
        """Turnを `running` で作成し、マスク済みの入力を保存する。

        Raises:
            AppError: Session不正（404）、message不正（400）、実行中のTurnあり（409）。
        """
        # 2. Sessionの所有権。アーカイブ済みには新しいTurnを開始できない。
        async with self._ctx.session_factory() as session:
            current = await SessionRepository(session).get_parent(auth.marketer_id, session_id)
        if current is None or current.archived_at is not None:
            raise AppError("AGENT_SESSION_NOT_FOUND")
        # 3. Request Bodyの検証。不正な場合はTurnを作成しない。
        message = self._validate_message(await body_loader())
        masked = mask_text(message)
        now = self._ctx.clock.now()
        # 4. Session行をロックし、復旧 → 実行中の確認 → Turn作成を1つの短いTransactionで行う。
        async with self._ctx.session_factory() as session, session.begin():
            sessions, turns = SessionRepository(session), TurnRepository(session)
            locked = await sessions.get_parent(auth.marketer_id, session_id, lock=True)
            if locked is None or locked.archived_at is not None:
                raise AppError("AGENT_SESSION_NOT_FOUND")
            threshold = now - timedelta(seconds=self._ctx.settings.stale_turn_seconds)
            recovered = await turns.recover_stale(
                session_id,
                threshold=threshold,
                now=now,
                message=DEFAULT_MESSAGES["TURN_INTERRUPTED"],
            )
            if recovered:
                _log.warning(
                    "turn_interrupted_recovered", session_id=session_id, turn_ids=recovered
                )
            if await turns.has_active_chat_turn(session_id):
                raise AppError("TURN_IN_PROGRESS")
            turn = await turns.create_turn(session_id, now)
            await turns.append_item(
                turn.id,
                key="user-message",
                item_type=AgentItemType.USER_MESSAGE,
                source=AgentContentSource.USER_INPUT,
                content={"text": masked},
                now=now,
            )
            title = masked.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
            await sessions.touch(session_id, now, title=title[:SESSION_TITLE_LENGTH])
            return PreparedTurn(auth, session_id, turn.id, turn.turn_number, now, masked)

    def _validate_message(self, raw_body: bytes) -> str:
        request = validate_model(MessageRequest, parse_json_object(raw_body))
        message = request.message.strip()
        field_error: FieldError | None = None
        if not message:
            field_error = {
                "field": "message",
                "code": "REQUIRED",
                "message": "メッセージを入力してください。",
            }
        elif len(message) > self._ctx.settings.message_max_length:
            field_error = {
                "field": "message",
                "code": "TOO_LONG",
                "message": (
                    f"メッセージは{self._ctx.settings.message_max_length:,}文字以内で"
                    "入力してください。"
                ),
            }
        if field_error is not None:
            raise AppError("INVALID_ARGUMENT", field_errors=[field_error])
        return message

    async def execute(self, prepared: PreparedTurn, reporter: ProgressReporter) -> TurnView:
        """Agentのループを実行し、Turnを終端状態へ更新して、最終状態のTurnを返す。

        Turnの実行中は、DBのTransactionとロックを保持しない。
        """
        error_code: str | None = None
        reply: str | None = None
        elapsed = (self._ctx.clock.now() - prepared.started_at).total_seconds()
        remaining = max(0.0, self._ctx.settings.turn_time_limit_seconds - elapsed)
        try:
            async with asyncio.timeout(remaining):
                context = await AgentContextBuilder(self._ctx).build(
                    prepared.session_id, prepared.turn_id
                )
                run_input = AgentRunInput(
                    session_id=prepared.session_id,
                    turn_id=prepared.turn_id,
                    marketer_id=prepared.auth.marketer_id,
                    company_id=prepared.auth.company_id,
                    message=prepared.message,
                    context=context,
                    tools=ToolExecutor(
                        self._ctx,
                        marketer_id=prepared.auth.marketer_id,
                        company_id=prepared.auth.company_id,
                        session_id=prepared.session_id,
                        turn_id=prepared.turn_id,
                        reporter=reporter,
                        agent_context=context,
                    ),
                )
                output = await self._ctx.agent_runner.run(run_input, reporter)
            reply = output.reply
        except TimeoutError:
            error_code = "TURN_TIME_LIMIT_EXCEEDED"
        except ContextCompactionError:
            error_code = "CONTEXT_COMPACTION_FAILED"
        except AgentRunError as error:
            error_code = error.code if error.code in ERROR_SPECS else "AGENT_EXECUTION_FAILED"
        except Exception as error:  # noqa: BLE001 - Agent実行の失敗はTurnの failed として保存する
            _log.error("agent_execution_failed", error=safe_error_text(error))
            error_code = "AGENT_EXECUTION_FAILED"
        return await self._finish(prepared, reply, error_code)

    async def _finish(
        self, prepared: PreparedTurn, reply: str | None, error_code: str | None
    ) -> TurnView:
        now = self._ctx.clock.now()
        async with self._ctx.session_factory() as session, session.begin():
            turns = TurnRepository(session)
            if error_code is None:
                # 回答を先に追記し、最後にTurnを終端化する。どちらもrunningを条件とする。
                if reply is not None:
                    appended = await turns.append_item_if_running(
                        prepared.turn_id,
                        key="assistant-message",
                        item_type=AgentItemType.ASSISTANT_MESSAGE,
                        source=AgentContentSource.AGENT_OUTPUT,
                        content={"text": mask_text(reply)},
                        now=now,
                    )
                    if appended is not None:
                        await turns.finish_turn(
                            prepared.turn_id, status=AgentTurnStatus.COMPLETED, now=now
                        )
            else:
                status = (
                    AgentTurnStatus.BLOCKED
                    if error_code == "TURN_BLOCKED"
                    else AgentTurnStatus.FAILED
                )
                await turns.finish_turn(
                    prepared.turn_id,
                    status=status,
                    now=now,
                    error_code=error_code,
                    error_message=DEFAULT_MESSAGES[error_code],
                )
        view = await TurnViewLoader(self._ctx).load(prepared.session_id, prepared.turn_id)
        if view is None:  # 作成済みのTurnが消えることはないため、到達しない。
            raise AppError("INTERNAL_ERROR")
        return view
