"""Agentの実行インターフェース。

フェーズ1では、固定応答を返す `StubAgentRunner` だけを提供する。
OpenAI Agents SDK によるループ（Firewall・Guardrail・子Agent）は、このProtocolを実装して差し替える。
"""

from dataclasses import dataclass
from typing import Literal, Protocol

STUB_REPLY = "（スタブ応答）Agentの実行は未実装です。メッセージは履歴へ保存されました。"

ActivityKind = Literal["tool", "subagent"]
ActivityStatus = Literal["succeeded", "failed", "blocked"]


@dataclass(frozen=True)
class AgentRunInput:
    """Agent実行の入力。権限に関わる値は認証済みContextから決める。"""

    session_id: int
    turn_id: int
    marketer_id: int
    company_id: int
    message: str


@dataclass(frozen=True)
class AgentRunOutput:
    """Agentの最終回答。"""

    reply: str


class AgentRunError(Exception):
    """Agentの実行を継続できない。`code` は API_DESIGN 10章のエラーコード。"""

    def __init__(self, code: str) -> None:
        """エラーコードを保持する。"""
        super().__init__(code)
        self.code = code


class ProgressReporter(Protocol):
    """ToolとサブエージェントのCallの進捗を通知する（SSE用）。"""

    def activity_started(
        self, kind: ActivityKind, name: str, parent_activity_id: str | None = None
    ) -> str:
        """実行の開始を通知し、`activity_id` を返す。"""
        ...

    def activity_finished(self, activity_id: str, status: ActivityStatus) -> None:
        """実行の終了を通知する。"""
        ...


class AgentRunner(Protocol):
    """親AgentのTurnを実行する。"""

    async def run(self, run_input: AgentRunInput, reporter: ProgressReporter) -> AgentRunOutput:
        """Turnを実行して最終回答を返す。

        Raises:
            AgentRunError: 実行を継続できない場合。
        """
        ...


class StubAgentRunner:
    """固定応答を返す仮のAgent。"""

    async def run(self, run_input: AgentRunInput, reporter: ProgressReporter) -> AgentRunOutput:
        """固定応答を返す。"""
        del run_input, reporter
        return AgentRunOutput(reply=STUB_REPLY)
