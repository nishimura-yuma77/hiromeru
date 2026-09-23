"""親Turnと子Agentで共有する実行budget。"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from agent_runtime.runner import AgentRunError


class _Clock(Protocol):
    def now(self) -> datetime: ...


@dataclass
class TurnBudget:
    """時間、論理step、確定USD costを親Turn単位で管理する。"""

    started_at: datetime
    clock: _Clock
    time_limit_seconds: float
    max_steps: int
    max_cost_usd: Decimal
    steps: int = 0
    cost_usd: Decimal = Decimal("0")

    def check(self) -> None:
        """操作前に time、steps、cost の順で上限を検査する。"""
        if (self.clock.now() - self.started_at).total_seconds() >= self.time_limit_seconds:
            raise AgentRunError("TURN_TIME_LIMIT_EXCEEDED")
        if self.steps >= self.max_steps:
            raise AgentRunError("TURN_STEP_LIMIT_EXCEEDED")
        if self.cost_usd >= self.max_cost_usd:
            raise AgentRunError("TURN_COST_LIMIT_EXCEEDED")

    def consume_step(self) -> None:
        """LLM request、論理Tool Call、compactionの直前に1 step消費する。"""
        self.check()
        self.steps += 1

    def add_cost(self, cost: Decimal) -> None:
        """確定costを加算し、超過した出力を不採用にする。"""
        self.cost_usd += cost
        if self.cost_usd > self.max_cost_usd:
            raise AgentRunError("TURN_COST_LIMIT_EXCEEDED")
