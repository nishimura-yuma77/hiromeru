"""テストで使う外部依存の代替（時刻・Embedding・X API・待機）。"""

import asyncio
import hashlib
import random
from datetime import UTC, datetime, timedelta

from agent_runtime.runner import AgentRunInput, AgentRunOutput, ProgressReporter
from clients.errors import EmbeddingError, XApiOutcomeUnknownError, XApiRejectedError
from clients.x_api import XPostResult
from domain.constants import EMBEDDING_DIMENSIONS


class FixedClock:
    """任意に進められる時計。"""

    def __init__(self) -> None:
        """現在時刻（秒未満を切り捨てたもの）から始める。"""
        self._now = datetime.now(UTC).replace(microsecond=0)

    def now(self) -> datetime:
        """現在の（固定された）UTC時刻を返す。"""
        return self._now

    def advance(self, seconds: float) -> None:
        """時刻を進める。"""
        self._now += timedelta(seconds=seconds)


def vector_for(text: str) -> list[float]:
    """同じ文字列から、常に同じ単位ベクトルを作る。"""
    seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
    generator = random.Random(seed)  # noqa: S311
    values = [generator.uniform(-1.0, 1.0) for _ in range(EMBEDDING_DIMENSIONS)]
    norm = sum(value * value for value in values) ** 0.5
    return [value / norm for value in values]


class FakeEmbedding:
    """決定的なEmbedding。失敗させることもできる。"""

    def __init__(self) -> None:
        """呼び出しの記録を空にする。"""
        self.calls: list[str] = []
        self.fail = False
        self.block_next: asyncio.Event | None = None
        self.blocked = asyncio.Event()

    async def embed(self, text: str) -> list[float]:
        """文字列に対応するベクトルを返す。`block_next` があれば次の1回だけ解放まで待つ。"""
        self.calls.append(text)
        gate, self.block_next = self.block_next, None
        if gate is not None:
            self.blocked.set()
            await gate.wait()
        if self.fail:
            raise EmbeddingError("fake embedding failure")
        return vector_for(text)


class FakeXApi:
    """X APIの代替。次の結果を `outcome` で指定する。"""

    def __init__(self) -> None:
        """既定は成功。"""
        self.calls: list[str] = []
        self.outcome: str = "ok"
        self.rejected_status = 403
        self.gate: asyncio.Event | None = None
        self.started = asyncio.Event()
        self._counter = 0

    async def post(self, text: str) -> XPostResult:
        """`outcome` に従って結果を返す。`gate` があれば、解放されるまで待つ。"""
        self.calls.append(text)
        self.started.set()
        if self.gate is not None:
            await self.gate.wait()
        if self.outcome == "rejected":
            raise XApiRejectedError(self.rejected_status)
        if self.outcome == "unknown":
            raise XApiOutcomeUnknownError("fake unknown")
        if self.outcome == "unexpected":
            raise RuntimeError("fake unexpected")
        self._counter += 1
        return XPostResult(x_post_id=f"x-{id(self)}-{self._counter}")


async def no_sleep(_seconds: float) -> None:
    """待機しない。"""


class FakeAgentRunner:
    """Agentの代替。返答・失敗・待機・進捗通知を指定できる。"""

    def __init__(self) -> None:
        """既定は固定の返答。"""
        self.reply = "テスト応答"
        self.error: Exception | None = None
        self.gate: asyncio.Event | None = None
        self.hang = False
        self.activities: list[tuple[str, str]] = []
        self.started = asyncio.Event()
        self.inputs: list[AgentRunInput] = []

    async def run(self, run_input: AgentRunInput, reporter: ProgressReporter) -> AgentRunOutput:
        """指定どおりに動作する。"""
        self.inputs.append(run_input)
        self.started.set()
        for kind, name in self.activities:
            activity_id = reporter.activity_started(kind, name)  # type: ignore[arg-type]
            reporter.activity_finished(activity_id, "succeeded")
        if self.hang:
            await asyncio.sleep(3600)
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            raise self.error
        return AgentRunOutput(reply=self.reply)
