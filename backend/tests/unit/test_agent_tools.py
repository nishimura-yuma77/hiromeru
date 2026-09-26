import pytest
from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError

from agent_runtime.business_tools import (
    GetMarketingMetricsInput,
    GetSessionItemsInput,
    SearchCampaignsInput,
)
from agent_runtime.proposal_tools import (
    ProposeCampaignInput,
    ProposeXPostInput,
    RunCampaignPlannerOutput,
)
from agent_runtime.runner import CampaignPlannerOutput, CampaignProposal
from agent_runtime.tools import (
    StrictToolModel,
    ToolCall,
    ToolDefinition,
    ToolErrorSpec,
    ToolRegistry,
    ToolRegistryError,
    ToolResult,
)
from core.config import Settings
from domain.enums import AgentContentSource, AgentContextClass, AgentType
from services.context import ServiceContext


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
        "errors": {"INVALID_ARGUMENT": ToolErrorSpec("invalid")},
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
                "auth_cookie_secret": SecretStr("test-secret-test-secret-test-secret-0123456789"),
                field: value,
            }
        )


def test_既定Registryは15ToolとAgent別allow_listを登録する(ctx: ServiceContext) -> None:
    expected = {
        "get_session_items",
        "search_long_term_memory",
        "save_long_term_memory",
        "delete_long_term_memory",
        "get_campaign",
        "search_campaigns",
        "get_post",
        "search_posts",
        "get_marketing_metrics",
        "web_search",
        "web_fetch",
        "run_campaign_planner",
        "run_content_creator",
        "propose_campaign",
        "propose_x_post",
    }
    assert {name for name in expected if ctx.tool_registry.get(name) is not None} == expected
    assert ctx.tool_registry.resolve(AgentType.CAMPAIGN_PLANNER, "get_session_items") is None
    assert ctx.tool_registry.resolve(AgentType.CONTENT_CREATOR, "save_long_term_memory") is None
    assert ctx.tool_registry.resolve(AgentType.CAMPAIGN_PLANNER, "search_campaigns") is not None
    memory_search = ctx.tool_registry.get("search_long_term_memory")
    assert memory_search is not None
    assert memory_search.result_source == AgentContentSource.LONG_TERM_MEMORY
    assert memory_search.result_context_class == AgentContextClass.UNTRUSTED_DATA
    assert memory_search.errors["EMBEDDING_FAILED"].retryable is True
    deletion = ctx.tool_registry.get("delete_long_term_memory")
    assert deletion is not None
    assert all(not spec.retryable for spec in deletion.errors.values())
    web_search = ctx.tool_registry.get("web_search")
    web_fetch = ctx.tool_registry.get("web_fetch")
    assert web_search is not None and web_fetch is not None
    assert web_search.result_source == AgentContentSource.WEB_SEARCH
    assert web_fetch.result_source == AgentContentSource.WEB_CONTENT
    assert web_search.result_context_class == AgentContextClass.UNTRUSTED_DATA
    assert web_fetch.result_context_class == AgentContextClass.UNTRUSTED_DATA
    assert web_fetch.errors["WEB_FETCH_FAILED"].retryable is True
    planner = ctx.tool_registry.get("run_campaign_planner")
    creator = ctx.tool_registry.get("run_content_creator")
    propose_campaign = ctx.tool_registry.get("propose_campaign")
    propose_post = ctx.tool_registry.get("propose_x_post")
    assert planner is not None and planner.uses_remaining_turn_time is True
    assert creator is not None and creator.uses_remaining_turn_time is True
    assert propose_campaign is not None and propose_campaign.terminal is True
    assert propose_post is not None and propose_post.terminal is True


def test_業務Tool_schemaは重複_XOR_naive日時と型変換を拒否する() -> None:
    with pytest.raises(ValidationError):
        GetSessionItemsInput.model_validate({"item_ids": [1, 1]})
    with pytest.raises(ValidationError):
        GetSessionItemsInput.model_validate({"item_ids": ["1"]})
    with pytest.raises(ValidationError):
        GetMarketingMetricsInput.model_validate({"campaign_id": 1, "post_id": 2})
    with pytest.raises(ValidationError):
        GetMarketingMetricsInput.model_validate({})
    with pytest.raises(ValidationError):
        SearchCampaignsInput.model_validate(
            {"query": "x", "limit": 1, "created_from": "2026-01-01T00:00:00"}
        )
    with pytest.raises(ValidationError):
        SearchCampaignsInput.model_validate(
            {"query": "x", "limit": 1, "created_from": "2026-01-01"}
        )


def test_子出力と提案入力はXOR_strict_時刻注入を検証する() -> None:
    proposal = {
        "id": None,
        "title": "採用施策",
        "target_profile": "経験者",
        "background": "応募減少",
        "objective": "応募増加",
        "plan": "働き方を訴求",
    }
    parsed = CampaignProposal.model_validate(proposal)
    missing = CampaignPlannerOutput.model_validate_json(
        '{"proposal":null,"missing_information":["採用人数"]}'
    )
    assert missing.missing_information == ("採用人数",)
    assert RunCampaignPlannerOutput(child_session_id=1, proposal=parsed).proposal == parsed
    with pytest.raises(ValidationError):
        RunCampaignPlannerOutput(child_session_id=1)
    with pytest.raises(ValidationError):
        RunCampaignPlannerOutput(
            child_session_id=1,
            proposal=parsed,
            missing_information=("対象",),
        )
    with pytest.raises(ValidationError):
        ProposeCampaignInput.model_validate({**proposal, "expected_updated_at": None})
    with pytest.raises(ValidationError):
        ProposeCampaignInput.model_validate({**proposal, "source_result_item_id": 1})
    with pytest.raises(ValidationError):
        ProposeXPostInput.model_validate(
            {
                "campaign_id": 1,
                "body": "本文",
                "landing_url": "https://example.com",
                "source_result_item_id": 1,
            }
        )
