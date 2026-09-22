import pytest
from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError

from agent_runtime.tools import (
    StrictToolModel,
    ToolCall,
    ToolDefinition,
    ToolRegistry,
    ToolRegistryError,
    ToolResult,
)
from core.config import Settings
from domain.enums import AgentContentSource, AgentContextClass, AgentType


class Input(StrictToolModel):
    text: str


class Output(StrictToolModel):
    value: str


class Handler:
    async def authorize(self, context: object, tool_input: BaseModel) -> bool:
        return True

    async def execute(self, context: object, tool_input: BaseModel) -> Output:
        return Output(value="ok")


def _definition(**changes: object) -> ToolDefinition:
    values = {
        "name": "sample_tool",
        "input_model": Input,
        "output_model": Output,
        "handler": Handler(),
        "allowed_agents": frozenset({AgentType.PARENT}),
        "result_source": AgentContentSource.DATABASE,
        "result_context_class": AgentContextClass.CONVERSATION,
    }
    values.update(changes)
    return ToolDefinition(**values)  # type: ignore[arg-type]


def test_RegistryはAgent別allow_listを適用し重複を拒否する() -> None:
    registry = ToolRegistry()
    definition = _definition()
    registry.register(definition)

    assert registry.resolve(AgentType.PARENT, "sample_tool") is definition
    assert registry.resolve(AgentType.CAMPAIGN_PLANNER, "sample_tool") is None
    assert registry.resolve(AgentType.PARENT, "unknown") is None
    with pytest.raises(ToolRegistryError):
        registry.register(definition)


def test_Tool固有schemaはstrictかつextra_forbid() -> None:
    with pytest.raises(ValidationError):
        Input.model_validate({"text": 1})
    with pytest.raises(ValidationError):
        Input.model_validate({"text": "ok", "extra": True})

    class LooseInput(BaseModel):
        model_config = ConfigDict(extra="ignore")
        text: str

    with pytest.raises(ToolRegistryError):
        ToolRegistry().register(_definition(input_model=LooseInput))


@pytest.mark.parametrize(
    "field", ["company_id", "marketer_id", "session_id", "turn_id", "agent_type"]
)
def test_Trusted値をTool引数へ注入できない(field: str) -> None:
    with pytest.raises(ValidationError):
        ToolCall(name="sample_tool", stable_key="provider-1", arguments={field: 1})
    with pytest.raises(ValidationError):
        ToolCall(
            name="sample_tool",
            stable_key="provider-2",
            arguments={"filters": [{field: 1}]},
        )


def test_ToolResultは成功と失敗を排他的にする() -> None:
    with pytest.raises(ValidationError):
        ToolResult(success=True, data=None, error=None)
    with pytest.raises(ValidationError):
        ToolResult(success=False, data={}, error=None)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tool_max_attempts", 0),
        ("tool_retry_backoff_seconds", 0),
        ("tool_attempt_timeout_seconds", 0),
        ("tool_attempt_timeout_seconds", 201),
    ],
)
def test_Tool実行設定は正数とTurn境界を検証する(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(
            {
                "auth_cookie_secret": SecretStr(
                    "test-secret-test-secret-test-secret-0123456789"
                ),
                field: value,
            }
        )
