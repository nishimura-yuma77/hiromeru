"""Agentの実行インターフェース。

フェーズ1では、固定応答を返す `StubAgentRunner` だけを提供する。
OpenAI Agents SDK によるループ（Firewall・Guardrail・子Agent）は、このProtocolを実装して差し替える。
"""

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any, Literal, Protocol

from pydantic import Field, JsonValue, StringConstraints, model_validator

from agent_runtime.tools import StrictToolModel, ToolInvoker

if TYPE_CHECKING:
    from agent_runtime.budget import TurnBudget
from domain.constants import (
    MAX_CAMPAIGN_TEXT_LENGTH,
    MAX_CAMPAIGN_TITLE_LENGTH,
    MAX_LANDING_URL_LENGTH,
)
from domain.enums import (
    AgentContentSource,
    AgentContextClass,
    AgentItemContextStatus,
    AgentItemType,
    AgentType,
)

STUB_REPLY = "（スタブ応答）Agentの実行は未実装です。メッセージは履歴へ保存されました。"

ActivityKind = Literal["tool", "subagent"]
ActivityStatus = Literal["succeeded", "failed", "blocked"]
ContextEntryKind = Literal["checkpoint", "item", "security_notice"]
ContextRole = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class AgentContextEntry:
    """DB表現から分離した、Runnerへ渡す順序付きContext要素。"""

    kind: ContextEntryKind
    role: ContextRole
    content: dict[str, Any]
    turn_id: int | None = None
    item_id: int | None = None
    item_type: AgentItemType | None = None
    context_class: AgentContextClass | None = None
    content_source: AgentContentSource | None = None
    context_status: AgentItemContextStatus | None = None
    source_item_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class AgentContext:
    """再構築済みのContextと、その決定論的な容量見積もり。"""

    entries: tuple[AgentContextEntry, ...]
    estimated_utf8_bytes: int


@dataclass(frozen=True)
class AgentRunInput:
    """Agent実行の入力。権限に関わる値は認証済みContextから決める。"""

    session_id: int
    turn_id: int
    marketer_id: int
    company_id: int
    message: str
    context: AgentContext
    tools: ToolInvoker
    budget: "TurnBudget | None" = None


@dataclass(frozen=True)
class AgentRunOutput:
    """最終回答またはterminal tool完了。"""

    reply: str | None
    llm_call_id: int | None = None
    terminal: bool = False

    def __post_init__(self) -> None:
        """排他的な終端形を検証する。"""
        if (self.reply is None) == (not self.terminal):
            raise ValueError("reply and terminal completion must be exclusive")
        if self.reply is not None and not self.reply.strip():
            raise ValueError("reply must not be empty")


_ProposalText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
_CampaignTitle = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_CAMPAIGN_TITLE_LENGTH),
]
_CampaignText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_CAMPAIGN_TEXT_LENGTH),
]


class CampaignProposal(StrictToolModel):
    """施策立案子Agentが返す施策案。時刻はアプリケーションが注入する。"""

    id: int | None = Field(default=None, gt=0)
    title: _CampaignTitle
    target_profile: _CampaignText
    background: _CampaignText
    objective: _CampaignText
    plan: _CampaignText


class XPostProposal(StrictToolModel):
    """コンテンツ制作子Agentが返す投稿案。"""

    campaign_id: int = Field(gt=0)
    body: _ProposalText
    landing_url: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_LANDING_URL_LENGTH),
    ]


class CampaignPlannerOutput(StrictToolModel):
    """施策立案子Agentの排他的な最終出力。"""

    proposal: CampaignProposal | None = None
    missing_information: tuple[_ProposalText, ...] | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _xor(self) -> "CampaignPlannerOutput":
        if (self.proposal is None) == (self.missing_information is None):
            raise ValueError("proposal and missing_information must be exclusive")
        return self


class ContentCreatorOutput(StrictToolModel):
    """コンテンツ制作子Agentの排他的な最終出力。"""

    proposal: XPostProposal | None = None
    missing_information: tuple[_ProposalText, ...] | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _xor(self) -> "ContentCreatorOutput":
        if (self.proposal is None) == (self.missing_information is None):
            raise ValueError("proposal and missing_information must be exclusive")
        return self


type ChildRunOutput = CampaignPlannerOutput | ContentCreatorOutput


@dataclass(frozen=True)
class ChildRunInput:
    """使い捨て子Agentの、認証済みかつ親budgetへ束縛された入力。"""

    agent_type: AgentType
    session_id: int
    turn_id: int
    parent_session_id: int
    parent_turn_id: int
    marketer_id: int
    company_id: int
    request: dict[str, JsonValue]
    context: AgentContext
    tools: ToolInvoker
    parent_started_at: datetime
    budget: "TurnBudget | None" = None


@dataclass(frozen=True)
class ChildRunResult:
    """子Agentの検証済み出力と生成元call。"""

    output: ChildRunOutput
    llm_call_id: int | None


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

    async def run_child(
        self, run_input: ChildRunInput, reporter: ProgressReporter
    ) -> ChildRunResult:
        """構造化された子Agentの最終結果だけを返す。"""
        ...


class StubAgentRunner:
    """固定応答を返す仮のAgent。"""

    async def run(self, run_input: AgentRunInput, reporter: ProgressReporter) -> AgentRunOutput:
        """固定応答を返す。"""
        del run_input, reporter
        return AgentRunOutput(reply=STUB_REPLY)

    async def run_child(
        self, run_input: ChildRunInput, reporter: ProgressReporter
    ) -> ChildRunResult:
        """実SDK未接続時は、追加情報が必要な構造化結果を返す。"""
        del reporter
        missing = ("実行可能な子Agentが設定されていません。",)
        if run_input.agent_type == AgentType.CAMPAIGN_PLANNER:
            output: ChildRunOutput = CampaignPlannerOutput(missing_information=missing)
        else:
            output = ContentCreatorOutput(missing_information=missing)
        return ChildRunResult(output=output, llm_call_id=None)
