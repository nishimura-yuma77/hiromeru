"""メッセージ送信のSSE（API_DESIGN 5.3）。

Turnを実行しているRequestを開いたままにして、進捗を返す。クライアントが切断しても、
Turnは中止せず終了まで実行する（進捗の送信だけを止める）。
"""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from agent_runtime.runner import ActivityKind, ActivityStatus
from api.serializers import serialize_turn, serialize_turn_projection
from core.logging import get_logger, safe_error_text
from domain.constants import SSE_KEEP_ALIVE_SECONDS
from domain.timefmt import format_utc
from services.turn_service import PreparedTurn, TurnService
from services.views import TurnView

_log = get_logger(__name__)
type _Event = tuple[str, dict[str, Any]]

# 実行中のタスクへの参照を保持し、GCによる中断を防ぐ（BE_STD 11章）。
_running_tasks: set[asyncio.Task[None]] = set()


class SseReporter:
    """進捗を、SSEのイベントキューへ流す `ProgressReporter`。"""

    def __init__(self, queue: asyncio.Queue[_Event | None]) -> None:
        """イベントキューを受け取る。"""
        self._queue = queue
        self._counter = 0

    def activity_started(
        self, kind: ActivityKind, name: str, parent_activity_id: str | None = None
    ) -> str:
        """実行の開始を通知する。`activity_id` はサーバーが採番する（a1, a2, ...）。"""
        self._counter += 1
        activity_id = f"a{self._counter}"
        self._queue.put_nowait(
            (
                "activity_started",
                {
                    "activity_id": activity_id,
                    "kind": kind,
                    "name": name,
                    "parent_activity_id": parent_activity_id,
                },
            )
        )
        return activity_id

    def activity_finished(self, activity_id: str, status: ActivityStatus) -> None:
        """実行の終了を通知する。"""
        self._queue.put_nowait(
            ("activity_finished", {"activity_id": activity_id, "status": status})
        )


class NullReporter:
    """進捗を通知しない `ProgressReporter`（JSON応答用）。"""

    def activity_started(
        self, kind: ActivityKind, name: str, parent_activity_id: str | None = None
    ) -> str:
        """何もしない。"""
        del kind, name, parent_activity_id
        return ""

    def activity_finished(self, activity_id: str, status: ActivityStatus) -> None:
        """何もしない。"""
        del activity_id, status


def format_event(event: str, data: dict[str, Any]) -> bytes:
    """SSEの1イベントを組み立てる。"""
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n".encode()


async def _run_turn(
    service: TurnService,
    prepared: PreparedTurn,
    queue: asyncio.Queue[_Event | None],
    deadline: float | None,
) -> None:
    view: TurnView | None = None
    try:
        async with asyncio.timeout_at(deadline):
            view = await service.execute(prepared, SseReporter(queue))
    except TimeoutError:
        view = await asyncio.shield(
            service.fail_running(prepared, "TURN_TIME_LIMIT_EXCEEDED")
        )
    except asyncio.CancelledError:
        await asyncio.shield(service.fail_running(prepared, "AGENT_EXECUTION_FAILED"))
        raise
    except Exception as error:  # noqa: BLE001 - stream開始後は固定Errorへ変換する
        _log.error("turn_stream_failed", error=safe_error_text(error))
        view = await asyncio.shield(service.fail_running(prepared, "AGENT_EXECUTION_FAILED"))
    assert view is not None  # noqa: S101 - 上の全経路で確定する内部不変条件
    try:
        payload = serialize_turn(view)
    except Exception as error:  # noqa: BLE001 - Serializer障害でも終端Eventを保証する
        _log.error("turn_stream_serialize_failed", error=safe_error_text(error))
        payload = serialize_turn_projection(view)
    queue.put_nowait(("turn_finished", payload))
    queue.put_nowait(None)


async def stream_turn(
    service: TurnService, prepared: PreparedTurn, deadline: float | None = None
) -> AsyncIterator[bytes]:
    """`turn_started` から `turn_finished` までのSSEを返す。15秒ごとにkeep-aliveを送る。"""
    queue: asyncio.Queue[_Event | None] = asyncio.Queue()
    task = asyncio.create_task(_run_turn(service, prepared, queue, deadline))
    _running_tasks.add(task)
    task.add_done_callback(_running_tasks.discard)
    yield format_event(
        "turn_started",
        {
            "agent_turn_id": prepared.turn_id,
            "turn_number": prepared.turn_number,
            "started_at": format_utc(prepared.started_at),
        },
    )
    while True:
        try:
            item = await asyncio.wait_for(queue.get(), timeout=SSE_KEEP_ALIVE_SECONDS)
        except TimeoutError:
            yield b": keep-alive\n\n"
            continue
        if item is None:
            return
        yield format_event(*item)
