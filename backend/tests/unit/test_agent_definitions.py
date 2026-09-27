import pytest
from pydantic import ValidationError

from agent_runtime import definitions
from agent_runtime.definitions import (
    AGENT_DEFINITIONS,
    AgentDefinition,
    get_agent_definition,
    validate_agent_definitions,
)
from api.container import build_default_context
from core.config import Settings
from domain.enums import AgentType


def test_Agent定義はTool権限と出力形式に一致する() -> None:
    ctx = build_default_context(Settings(_env_file=None))  # type: ignore[call-arg]

    validate_agent_definitions(ctx.tool_registry, turn_time_limit_seconds=200)
    assert set(AGENT_DEFINITIONS) == set(AgentType)
    assert get_agent_definition(AgentType.CAMPAIGN_PLANNER).final_output_model is not None
    assert "propose_campaign" not in get_agent_definition(AgentType.CAMPAIGN_PLANNER).tool_names


def test_Agent定義は親の構造化出力と子の非構造化出力を拒否する() -> None:
    parent = get_agent_definition(AgentType.PARENT)
    child = get_agent_definition(AgentType.CAMPAIGN_PLANNER)

    with pytest.raises(ValidationError, match="parent must use a plain final"):
        AgentDefinition(
            agent_type=parent.agent_type,
            version=parent.version,
            instructions=parent.instructions,
            model=parent.model,
            tool_names=parent.tool_names,
            final_output_model=child.final_output_model,
        )
    with pytest.raises(ValidationError, match="child must have a structured final"):
        AgentDefinition(
            agent_type=child.agent_type,
            version=child.version,
            instructions=child.instructions,
            model=child.model,
            tool_names=child.tool_names,
        )


def test_Agent定義がTool権限と食い違うと起動前に失敗する(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = build_default_context(Settings(_env_file=None))  # type: ignore[call-arg]
    child = get_agent_definition(AgentType.CAMPAIGN_PLANNER)
    monkeypatch.setattr(
        definitions,
        "AGENT_DEFINITIONS",
        {
            **AGENT_DEFINITIONS,
            AgentType.CAMPAIGN_PLANNER: child.model_copy(
                update={"tool_names": child.tool_names | {"propose_campaign"}}
            ),
        },
    )

    with pytest.raises(ValueError, match="agent tools do not match registry permissions"):
        validate_agent_definitions(ctx.tool_registry, turn_time_limit_seconds=200)
