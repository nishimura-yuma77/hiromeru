"""Agent会話API（API_DESIGN 5章）。"""

from typing import Annotated

from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from api.content_negotiation import accepts_event_stream
from api.deps import Authenticated, Context, CsrfProtected
from api.middleware import REQUEST_DEADLINE_KEY
from api.request_body import read_json_body
from api.responses import ok
from api.serializers import (
    serialize_history,
    serialize_session,
    serialize_session_list,
    serialize_turn,
)
from api.sse import NullReporter, stream_turn
from core.errors import AppError
from domain.constants import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT
from services.session_service import SessionService
from services.turn_service import TurnService

router = APIRouter(prefix="/api/v1/agent-sessions", tags=["agent"])

SessionId = Annotated[int, Path(gt=0)]
TurnId = Annotated[int, Path(gt=0)]
Limit = Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)]


@router.post("")
async def create_session(ctx: Context, auth: CsrfProtected) -> JSONResponse:
    """新しい親Sessionを作成する（Turnは作らない。Request Bodyは使わない）。"""
    return ok(serialize_session(await SessionService(ctx).create(auth)), 201)


@router.get("")
async def list_sessions(
    ctx: Context, auth: Authenticated, limit: Limit = DEFAULT_PAGE_LIMIT, cursor: str | None = None
) -> JSONResponse:
    """親Sessionを、最終更新日時の新しい順に返す。"""
    view = await SessionService(ctx).list(auth, limit=limit, cursor=cursor)
    return ok(serialize_session_list(view))


@router.get("/{session_id}")
async def get_history(
    session_id: SessionId,
    ctx: Context,
    auth: Authenticated,
    limit: Limit = DEFAULT_PAGE_LIMIT,
    before_turn_number: Annotated[int | None, Query(ge=1)] = None,
) -> JSONResponse:
    """Sessionの情報とTurnの履歴を返す。"""
    view = await SessionService(ctx).history(
        auth, session_id, limit=limit, before_turn_number=before_turn_number
    )
    return ok(serialize_history(view))


@router.get("/{session_id}/turns/{turn_id}")
async def get_turn(
    session_id: SessionId, turn_id: TurnId, ctx: Context, auth: Authenticated
) -> JSONResponse:
    """Turnの状態と表示対象のItemを返す。"""
    return ok(serialize_turn(await SessionService(ctx).get_turn(auth, session_id, turn_id)))


@router.post("/{session_id}/turns", response_model=None)
async def send_message(
    session_id: SessionId, request: Request, ctx: Context, auth: CsrfProtected
) -> JSONResponse | StreamingResponse:
    """ユーザーのメッセージで親AgentのTurnを実行する。`Accept` によりJSONまたはSSEで返す。"""
    service = TurnService(ctx)
    prepared = await service.begin(auth, session_id, lambda: read_json_body(request))
    if accepts_event_stream(request.headers.get("accept")):
        return StreamingResponse(
            stream_turn(service, prepared, request.scope.get(REQUEST_DEADLINE_KEY)),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
        )
    view = await service.execute(prepared, NullReporter())
    if view.status == "completed":
        return ok(serialize_turn(view), 201)
    code = view.error.code if view.error is not None else "INTERNAL_ERROR"
    message = view.error.message if view.error is not None else None
    raise AppError(code, message, agent_turn_id=view.agent_turn_id)
