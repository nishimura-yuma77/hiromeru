"""Agent ToolのSDK・DB非依存な型と登録Registry。"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from domain.enums import AgentContentSource, AgentContextClass, AgentTurnStatus, AgentType

if TYPE_CHECKING:
    from agent_runtime.runner import AgentContext

_TRUSTED_FIELD_NAMES = frozenset(
    {
        "agent_type",
        "company_id",
        "marketer_id",
        "parent_activity_id",
        "parent_session_id",
        "progress_reporter",
        "session_id",
        "turn_id",
    }
)


def _contains_trusted_field(value: Any) -> bool:  # noqa: ANN401 - 任意のJSON値を再帰検査する
    if isinstance(value, dict):
        return bool(_TRUSTED_FIELD_NAMES.intersection(value)) or any(
            _contains_trusted_field(item) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_trusted_field(item) for item in value)
    return False


class StrictToolModel(BaseModel):
    """Tool固有schemaの基底。暗黙変換と未知fieldを許可しない。"""

    model_config = ConfigDict(strict=True, extra="forbid")


class ToolProvenance(StrEnum):
    """Firewallへ渡してよい、内容を含まない出所分類。"""

    USER_INPUT = "user_input"
    AGENT_CONTEXT = "agent_context"
    TOOL_RESULT = "tool_result"
    SYSTEM = "system"


class ToolProvenanceRef(StrictToolModel):
    """Firewall判断に使った安全な出所参照。"""

    source: ToolProvenance
    item_id: int | None = Field(default=None, gt=0)


class ToolCall(StrictToolModel):
    """RunnerからExecutorへ渡す論理Tool Call。"""

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,99}$")
    stable_key: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9._:-]+$")
    arguments: dict[str, JsonValue]
    provenance: tuple[ToolProvenanceRef, ...] = ()

    @model_validator(mode="after")
    def _reject_trusted_fields(self) -> "ToolCall":
        """認証済みContextから決める値の注入を拒否する。"""
        if _contains_trusted_field(self.arguments):
            raise ValueError("trusted runtime fields cannot be tool arguments")
        return self


class ToolError(StrictToolModel):
    """Agentへ返せる固定文言だけのTool error。"""

    code: str
    message: str
    retryable: bool


@dataclass(frozen=True)
class ToolErrorSpec:
    """Tool定義が公開を許可する固定Error。"""

    message: str
    retryable: bool = False
    blocked: bool = False


class ToolDomainError(Exception):
    """HandlerからExecutorへ詳細を漏らさず伝える宣言済み業務Error。"""

    def __init__(
        self, code: str, message: str, *, retryable: bool = False, blocked: bool = False
    ) -> None:
        """固定code・文言・再試行可否を保持する。"""
        super().__init__(code)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.blocked = blocked


class ToolResult(StrictToolModel):
    """成功・失敗を排他的に表す共通Tool Result。"""

    success: bool
    data: dict[str, Any] | None
    error: ToolError | None

    @model_validator(mode="after")
    def _exclusive_result(self) -> "ToolResult":
        if self.success != (self.data is not None and self.error is None):
            raise ValueError("success result requires data; failure result requires error")
        if not self.success and (self.data is not None or self.error is None):
            raise ValueError("failure result requires only error")
        return self


class TrustedToolContext(StrictToolModel):
    """認証とDB正本からExecutorが組み立てるTrusted Runtime Context。"""

    company_id: int = Field(gt=0)
    marketer_id: int = Field(gt=0)
    session_id: int = Field(gt=0)
    parent_session_id: int | None = Field(default=None, gt=0)
    turn_id: int = Field(gt=0)
    agent_type: AgentType
    turn_status: AgentTurnStatus
    turn_started_at: datetime
    provenance: tuple[ToolProvenanceRef, ...] = ()
    budget: Any = Field(default=None, exclude=True)
    progress_reporter: Any = Field(default=None, exclude=True)
    parent_activity_id: str | None = Field(default=None, exclude=True)


class ToolHandler(Protocol):
    """Toolの認可と実処理。"""

    async def authorize(self, context: TrustedToolContext, tool_input: BaseModel) -> bool:
        """権限と業務条件を検査する。"""
        ...

    async def execute(self, context: TrustedToolContext, tool_input: BaseModel) -> Any:  # noqa: ANN401
        """Toolを1回実行し、Tool固有出力を返す。"""
        ...


@dataclass(frozen=True)
class ToolPreparation:
    """Firewall前にDB/URL検証したTool固有入力。"""

    execution_input: Any
    masked_arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolDefinition:
    """後続Issueが登録するTool定義。"""

    name: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    handler: ToolHandler
    allowed_agents: frozenset[AgentType]
    result_source: AgentContentSource
    result_context_class: AgentContextClass
    errors: Mapping[str, ToolErrorSpec] = field(default_factory=dict)
    terminal: bool = False
    input_error_code: str = "INVALID_ARGUMENT"
    uses_remaining_turn_time: bool = False
    activity_kind: Literal["tool", "subagent"] = "tool"


class ToolRegistryError(ValueError):
    """Tool定義が安全でない、または重複している。"""


class ToolRegistry:
    """AgentType別allow-listを持つTool Registry。"""

    def __init__(self) -> None:
        """空のallow-listを作る。"""
        self._definitions: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        """Strict schemaを検査してToolを一意に登録する。"""
        if definition.name in self._definitions:
            raise ToolRegistryError(f"duplicate tool definition: {definition.name}")
        if not definition.allowed_agents:
            raise ToolRegistryError("allowed_agents must not be empty")
        # ToolCall自身で同じname制約を検証する。
        ToolCall(name=definition.name, stable_key="registration", arguments={})
        for model in (definition.input_model, definition.output_model):
            config: Mapping[str, Any] = model.model_config
            if config.get("strict") is not True or config.get("extra") != "forbid":
                raise ToolRegistryError("tool schemas must use strict=True and extra='forbid'")
        if _TRUSTED_FIELD_NAMES.intersection(definition.input_model.model_fields):
            raise ToolRegistryError("tool input schema cannot declare trusted runtime fields")
        self._definitions[definition.name] = definition

    def get(self, name: str) -> ToolDefinition | None:
        """登録済み定義を返す。"""
        return self._definitions.get(name)

    def resolve(self, agent_type: AgentType, name: str) -> ToolDefinition | None:
        """指定Agentに許可された定義だけを返す。"""
        definition = self.get(name)
        if definition is None or agent_type not in definition.allowed_agents:
            return None
        return definition

    def allowed(self, agent_type: AgentType) -> tuple[ToolDefinition, ...]:
        """指定Agentへ公開できる定義を登録順で返す。"""
        return tuple(
            definition
            for definition in self._definitions.values()
            if agent_type in definition.allowed_agents
        )


class TransientToolError(Exception):
    """副作用の結果が既知で、安全に再試行できる一時エラー。"""


class ToolInvoker(Protocol):
    """実RunnerがTool Call時に利用するTurn専用境界。"""

    async def invoke(
        self,
        call: ToolCall,
        parent_activity_id: str | None = None,
        *,
        origin_llm_call_id: int | None = None,
    ) -> ToolResult:
        """Toolを検証・認可・Firewall検査して実行する。"""
        ...

    def replace_context(self, context: "AgentContext") -> None:
        """Tool実行後や隔離後にprovenance照合用Contextを更新する。"""
        ...
