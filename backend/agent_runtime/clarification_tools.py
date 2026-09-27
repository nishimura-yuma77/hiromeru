"""親Agentがユーザーへ構造化した質問を提示するTool。"""

from typing import Annotated, cast

from pydantic import Field, StringConstraints, field_validator

from agent_runtime.tools import (
    StrictToolModel,
    ToolDefinition,
    ToolErrorSpec,
    ToolHandler,
    ToolRegistry,
    TrustedToolContext,
)
from domain.enums import AgentContentSource, AgentContextClass, AgentType

_Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class AskUserInput(StrictToolModel):
    """ユーザーが答えられる、順序付きの最大3問。"""

    questions: list[_Question] = Field(min_length=1, max_length=3)

    @field_validator("questions")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("questions must be unique")
        return value


class AskUserOutput(AskUserInput):
    """表示する質問のみを含む、終端Toolの結果。"""


class AskUserHandler:
    """権限を確認して質問を返す。外部作用はない。"""

    async def authorize(self, context: TrustedToolContext, tool_input: AskUserInput) -> bool:
        """親Agentの親Sessionに限る。"""
        del tool_input
        return context.agent_type == AgentType.PARENT and context.parent_session_id is None

    async def execute(self, context: TrustedToolContext, tool_input: AskUserInput) -> AskUserOutput:
        """検証済みの質問をそのまま返す。"""
        del context
        return AskUserOutput(questions=tool_input.questions)


def register_clarification_tool(registry: ToolRegistry) -> None:
    """質問Toolを親Agentのallow-listに登録する。"""
    registry.register(
        ToolDefinition(
            name="ask_user",
            input_model=AskUserInput,
            output_model=AskUserOutput,
            handler=cast(ToolHandler, AskUserHandler()),
            allowed_agents=frozenset({AgentType.PARENT}),
            result_source=AgentContentSource.AGENT_OUTPUT,
            result_context_class=AgentContextClass.CONVERSATION,
            errors={"INVALID_ARGUMENT": ToolErrorSpec("The tool input is invalid.")},
            terminal=True,
        )
    )
