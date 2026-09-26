import asyncio
from typing import Any, cast

import pytest
from sqlalchemy import func, select

from agent_runtime.executor import ToolExecutor
from agent_runtime.runner import (
    ActivityKind,
    ActivityStatus,
    CampaignPlannerOutput,
    CampaignProposal,
    ChildRunInput,
    ChildRunResult,
    ContentCreatorOutput,
    ProgressReporter,
    XPostProposal,
)
from agent_runtime.tools import ToolCall
from api.sse import NullReporter
from domain.enums import AgentContentSource, AgentItemType, AgentTurnStatus, AgentType
from domain.timefmt import format_utc
from models import AgentItem, AgentSession, AgentTurn, Campaign, Post
from repositories.agent import SessionRepository, TurnRepository
from services.agent_context import AgentContextBuilder
from services.context import ServiceContext
from tests.support.client import Account, campaign_body
from tests.support.db import archive_campaign
from tests.support.fakes import FakeAgentRunner, FixedClock


async def _turn(ctx: ServiceContext, account: Account, session_id: int) -> tuple[int, int]:
    async with ctx.session_factory() as session, session.begin():
        assert await SessionRepository(session).get_parent(
            account.marketer_id, session_id, lock=True
        )
        turn = await TurnRepository(session).create_turn(session_id, ctx.clock.now())
        item = await TurnRepository(session).append_item(
            turn.id,
            key="request",
            item_type=AgentItemType.USER_MESSAGE,
            source=AgentContentSource.USER_INPUT,
            content={"text": "採用施策を提案して"},
            now=ctx.clock.now(),
        )
    return turn.id, item.id


async def _executor(
    ctx: ServiceContext,
    account: Account,
    session_id: int,
    turn_id: int,
    reporter: ProgressReporter | None = None,
) -> ToolExecutor:
    context = await AgentContextBuilder(ctx).build(session_id, turn_id)
    return ToolExecutor(
        ctx,
        marketer_id=account.marketer_id,
        company_id=account.company_id,
        session_id=session_id,
        turn_id=turn_id,
        reporter=reporter or NullReporter(),
        agent_context=context,
    )


class _RecordingReporter:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, str | None]]] = []

    def activity_started(
        self, kind: ActivityKind, name: str, parent_activity_id: str | None = None
    ) -> str:
        activity_id = f"a{len([event for event in self.events if event[0] == 'started']) + 1}"
        self.events.append(
            (
                "started",
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
        self.events.append(("finished", {"activity_id": activity_id, "status": status}))


def _campaign_proposal(campaign_id: int | None = None) -> CampaignProposal:
    return CampaignProposal(
        id=campaign_id,
        title="経験者Webエンジニア採用",
        target_profile="20代後半のWebエンジニア",
        background="経験者採用の応募数が減少している",
        objective="応募数を増やす",
        plan="柔軟な働き方をXで訴求する",
    )


async def test_子Agent内ActivityはsubagentのActivityへ関連付ける(
    account: Account,
    ctx: ServiceContext,
    agent: FakeAgentRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = await account.create_session()
    turn_id, request_id = await _turn(ctx, account, session_id)
    reporter = _RecordingReporter()
    executor = await _executor(ctx, account, session_id, turn_id, reporter)
    original = agent.run_child

    async def run_child(
        run_input: ChildRunInput, child_reporter: ProgressReporter
    ) -> ChildRunResult:
        activity_id = child_reporter.activity_started("tool", "search_campaigns")
        child_reporter.activity_finished(activity_id, "succeeded")
        return await original(run_input, child_reporter)

    monkeypatch.setattr(agent, "run_child", run_child)
    result = await executor.invoke(
        ToolCall(
            name="run_campaign_planner",
            stable_key="planner-activity",
            arguments={"request_item_id": request_id},
        )
    )

    assert result.success is True
    started = [payload for event, payload in reporter.events if event == "started"]
    assert started == [
        {
            "activity_id": "a1",
            "kind": "subagent",
            "name": "run_campaign_planner",
            "parent_activity_id": None,
        },
        {
            "activity_id": "a2",
            "kind": "tool",
            "name": "search_campaigns",
            "parent_activity_id": "a1",
        },
    ]


async def test_Planner提案は子の最終結果だけを保存しUIへ投影する(
    account: Account, ctx: ServiceContext, agent: FakeAgentRunner
) -> None:
    session_id = await account.create_session()
    turn_id, request_id = await _turn(ctx, account, session_id)
    proposal = _campaign_proposal()
    agent.child_output = CampaignPlannerOutput(proposal=proposal)
    executor = await _executor(ctx, account, session_id, turn_id)

    run = await executor.invoke(
        ToolCall(
            name="run_campaign_planner",
            stable_key="planner-1",
            arguments={"request_item_id": request_id},
        )
    )
    assert run.success is True
    assert run.data is not None
    child_session_id = cast(int, run.data["child_session_id"])
    assert run.data["proposal"] == proposal.model_dump(mode="json")
    proposed = await executor.invoke(
        ToolCall(
            name="propose_campaign",
            stable_key="proposal-1",
            arguments=proposal.model_dump(mode="json"),
        )
    )
    assert proposed.success is True
    assert proposed.data is not None
    assert proposed.data["expected_updated_at"] is None

    async with ctx.session_factory() as session, session.begin():
        child = await session.get(AgentSession, child_session_id)
        assert child is not None
        assert child.agent == AgentType.CAMPAIGN_PLANNER
        assert child.parent_session_id == session_id
        child_turn = await session.scalar(
            select(AgentTurn).where(AgentTurn.session_id == child_session_id)
        )
        assert child_turn is not None and child_turn.status == AgentTurnStatus.COMPLETED
        items = list(
            (
                await session.execute(
                    select(AgentItem)
                    .where(AgentItem.agent_turn_id == child_turn.id)
                    .order_by(AgentItem.item_number)
                )
            ).scalars()
        )
        assert [item.item_type for item in items] == [
            AgentItemType.USER_MESSAGE,
            AgentItemType.ASSISTANT_MESSAGE,
        ]
        assert items[-1].content == agent.child_output.model_dump(mode="json")
        await TurnRepository(session).finish_turn(
            turn_id, status=AgentTurnStatus.COMPLETED, now=ctx.clock.now()
        )

    response = await account.client.get(f"/api/v1/agent-sessions/{session_id}/turns/{turn_id}")
    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert [item["type"] for item in items] == ["user_message", "campaign_proposal"]
    assert items[-1]["content"] == proposed.data

    child_history = await account.client.get(f"/api/v1/agent-sessions/{child_session_id}")
    assert child_history.status_code == 404
    assert (
        await account.client.get(f"/api/v1/agent-sessions/{child_session_id}/turns/{child_turn.id}")
    ).status_code == 404
    assert (
        await account.client.post(
            f"/api/v1/agent-sessions/{child_session_id}/turns", json={"message": "x"}
        )
    ).status_code == 404
    assert (
        await account.client.post(
            f"/api/v1/agent-sessions/{child_session_id}/campaigns",
            headers={"Idempotency-Key": "child-denied"},
            json=campaign_body(),
        )
    ).status_code == 404
    listed = await account.client.get("/api/v1/agent-sessions")
    assert child_session_id not in {
        item["session_id"] for item in listed.json()["data"]["sessions"]
    }


async def test_Plannerは現在依頼と親会話を分離して子へ渡す(
    account: Account, ctx: ServiceContext, agent: FakeAgentRunner
) -> None:
    session_id = await account.create_session()
    async with ctx.session_factory() as session, session.begin():
        previous = await TurnRepository(session).create_turn(session_id, ctx.clock.now())
        await TurnRepository(session).append_item(
            previous.id,
            key="previous-user",
            item_type=AgentItemType.USER_MESSAGE,
            source=AgentContentSource.USER_INPUT,
            content={"text": "エンジニア向け採用施策を考えて"},
            now=ctx.clock.now(),
        )
        await TurnRepository(session).append_item(
            previous.id,
            key="previous-assistant",
            item_type=AgentItemType.ASSISTANT_MESSAGE,
            source=AgentContentSource.AGENT_OUTPUT,
            content={"text": "採用施策の草案です"},
            now=ctx.clock.now(),
        )
        await TurnRepository(session).finish_turn(
            previous.id, status=AgentTurnStatus.COMPLETED, now=ctx.clock.now()
        )
    turn_id, request_id = await _turn(ctx, account, session_id)
    executor = await _executor(ctx, account, session_id, turn_id)

    result = await executor.invoke(
        ToolCall(
            name="run_campaign_planner",
            stable_key="planner-context",
            arguments={"request_item_id": request_id},
        )
    )

    assert result.success is True
    assert agent.child_inputs[-1].request == {
        "request_item_id": request_id,
        "request": "採用施策を提案して",
        "conversation": [
            {"role": "user", "text": "エンジニア向け採用施策を考えて"},
            {"role": "assistant", "text": "採用施策の草案です"},
        ],
    }


async def test_ContentCreator提案はCampaign時刻を返さず業務表を書き換えない(
    account: Account, ctx: ServiceContext, agent: FakeAgentRunner
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    turn_id, request_id = await _turn(ctx, account, session_id)
    proposal = XPostProposal(
        campaign_id=campaign_id,
        body="柔軟な働き方を大切にするエンジニアを募集しています。",
        landing_url="https://example.com/jobs/engineer",
    )
    agent.child_output = ContentCreatorOutput(proposal=proposal)
    executor = await _executor(ctx, account, session_id, turn_id)
    async with ctx.session_factory() as session:
        before_campaigns = await session.scalar(select(func.count()).select_from(Campaign))
        before_posts = await session.scalar(select(func.count()).select_from(Post))

    run = await executor.invoke(
        ToolCall(
            name="run_content_creator",
            stable_key="creator-1",
            arguments={"campaign_id": campaign_id, "request_item_id": request_id},
        )
    )
    assert run.success is True
    proposed = await executor.invoke(
        ToolCall(
            name="propose_x_post",
            stable_key="post-proposal-1",
            arguments=proposal.model_dump(mode="json"),
        )
    )
    assert proposed.success is True
    assert proposed.data == proposal.model_dump(mode="json")
    async with ctx.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Campaign)) == before_campaigns
        assert await session.scalar(select(func.count()).select_from(Post)) == before_posts


async def test_ContentCreatorが対象外Campaignを返すとchild完了前に拒否する(
    account: Account, ctx: ServiceContext, agent: FakeAgentRunner
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    other_campaign_id = await account.create_campaign(session_id)
    turn_id, request_id = await _turn(ctx, account, session_id)
    agent.child_output = ContentCreatorOutput(
        proposal=XPostProposal(
            campaign_id=other_campaign_id,
            body="対象外の施策に対する投稿案です。",
            landing_url="https://example.com/jobs",
        )
    )
    executor = await _executor(ctx, account, session_id, turn_id)

    result = await executor.invoke(
        ToolCall(
            name="run_content_creator",
            stable_key="creator-mismatched-campaign",
            arguments={"campaign_id": campaign_id, "request_item_id": request_id},
        )
    )

    assert result.error is not None and result.error.code == "INVALID_SUBAGENT_OUTPUT"
    async with ctx.session_factory() as session:
        child_turn = await session.scalar(
            select(AgentTurn)
            .join(AgentSession, AgentSession.id == AgentTurn.session_id)
            .where(AgentSession.parent_session_id == session_id)
        )
    assert child_turn is not None
    assert child_turn.status == AgentTurnStatus.FAILED


async def test_missing情報は成功し提案元には使えない(
    account: Account, ctx: ServiceContext, agent: FakeAgentRunner
) -> None:
    session_id = await account.create_session()
    turn_id, request_id = await _turn(ctx, account, session_id)
    agent.child_output = CampaignPlannerOutput(missing_information=("採用人数",))
    executor = await _executor(ctx, account, session_id, turn_id)
    result = await executor.invoke(
        ToolCall(
            name="run_campaign_planner",
            stable_key="planner-missing",
            arguments={"request_item_id": request_id},
        )
    )
    assert result.success is True
    assert result.data is not None and result.data["proposal"] is None
    invalid = await executor.invoke(
        ToolCall(
            name="propose_campaign",
            stable_key="proposal-without-source",
            arguments=_campaign_proposal().model_dump(mode="json"),
        )
    )
    assert invalid.success is False
    assert invalid.error is not None and invalid.error.code == "INVALID_PROPOSAL_SOURCE"


async def test_保存済みProposalがSchema不正ならTurn表示から除外する(
    account: Account, ctx: ServiceContext, agent: FakeAgentRunner
) -> None:
    session_id = await account.create_session()
    turn_id, request_id = await _turn(ctx, account, session_id)
    proposal = _campaign_proposal()
    agent.child_output = CampaignPlannerOutput(proposal=proposal)
    executor = await _executor(ctx, account, session_id, turn_id)
    await executor.invoke(
        ToolCall(
            name="run_campaign_planner",
            stable_key="planner-malformed-view",
            arguments={"request_item_id": request_id},
        )
    )
    proposed = await executor.invoke(
        ToolCall(
            name="propose_campaign",
            stable_key="proposal-malformed-view",
            arguments=proposal.model_dump(mode="json"),
        )
    )
    assert proposed.success is True
    async with ctx.session_factory() as session, session.begin():
        call = await session.scalar(
            select(AgentItem).where(
                AgentItem.agent_turn_id == turn_id,
                AgentItem.idempotency_key == "tool:proposal-malformed-view",
            )
        )
        assert call is not None
        result = await session.scalar(
            select(AgentItem).where(AgentItem.related_tool_call_item_id == call.id)
        )
        assert result is not None
        result.content = {"success": True, "data": {"title": "incomplete"}, "error": None}
        await TurnRepository(session).finish_turn(
            turn_id, status=AgentTurnStatus.COMPLETED, now=ctx.clock.now()
        )

    response = await account.client.get(f"/api/v1/agent-sessions/{session_id}/turns/{turn_id}")
    assert [item["type"] for item in response.json()["data"]["items"]] == ["user_message"]


@pytest.mark.parametrize("malformed", [{"proposal": {}}, object()])
async def test_不正な子出力はchild_failedになり内部詳細を返さない(
    malformed: object,
    account: Account,
    ctx: ServiceContext,
    agent: FakeAgentRunner,
) -> None:
    session_id = await account.create_session()
    turn_id, request_id = await _turn(ctx, account, session_id)
    agent.child_output = cast(Any, malformed)
    executor = await _executor(ctx, account, session_id, turn_id)
    result = await executor.invoke(
        ToolCall(
            name="run_campaign_planner",
            stable_key="planner-malformed",
            arguments={"request_item_id": request_id},
        )
    )
    assert result.success is False
    assert result.error is not None and result.error.code == "INVALID_SUBAGENT_OUTPUT"
    async with ctx.session_factory() as session:
        child_turn = await session.scalar(
            select(AgentTurn)
            .join(AgentSession, AgentSession.id == AgentTurn.session_id)
            .where(AgentSession.parent_session_id == session_id)
        )
        assert child_turn is not None
        assert child_turn.status == AgentTurnStatus.FAILED
        assert child_turn.error_code == "SUBAGENT_FAILED"


async def test_子Runner例外と最終出力上限超過は固定Errorでchildをfailedにする(
    account: Account,
    ctx: ServiceContext,
    agent: FakeAgentRunner,
) -> None:
    session_id = await account.create_session()
    turn_id, request_id = await _turn(ctx, account, session_id)
    executor = await _executor(ctx, account, session_id, turn_id)
    agent.child_error = RuntimeError("private runner detail")
    failed = await executor.invoke(
        ToolCall(
            name="run_campaign_planner",
            stable_key="planner-error",
            arguments={"request_item_id": request_id},
        )
    )
    assert failed.error is not None
    assert failed.error.code == "SUBAGENT_FAILED"
    assert "private" not in failed.error.message

    agent.child_error = None
    ctx.settings.subagent_final_output_max_bytes = 100
    agent.child_output = CampaignPlannerOutput(
        proposal=_campaign_proposal().model_copy(update={"plan": "長" * 500})
    )
    oversized = await executor.invoke(
        ToolCall(
            name="run_campaign_planner",
            stable_key="planner-oversized",
            arguments={"request_item_id": request_id},
        )
    )
    assert oversized.error is not None
    assert oversized.error.code == "INVALID_SUBAGENT_OUTPUT"


async def test_親Turn時間切れでcancelされた子Turnをfailedにする(
    account: Account, ctx: ServiceContext, agent: FakeAgentRunner
) -> None:
    session_id = await account.create_session()
    turn_id, request_id = await _turn(ctx, account, session_id)
    executor = await _executor(ctx, account, session_id, turn_id)
    agent.child_gate = asyncio.Event()
    ctx.settings.turn_time_limit_seconds = 0.5

    result = await executor.invoke(
        ToolCall(
            name="run_campaign_planner",
            stable_key="planner-timeout",
            arguments={"request_item_id": request_id},
        )
    )

    assert result.error is not None and result.error.code == "TOOL_EXECUTION_FAILED"
    async with ctx.session_factory() as session:
        child_turn = await session.scalar(
            select(AgentTurn)
            .join(AgentSession, AgentSession.id == AgentTurn.session_id)
            .where(AgentSession.parent_session_id == session_id)
        )
    assert child_turn is not None
    assert child_turn.status == AgentTurnStatus.FAILED


async def test_提案Toolの入力schema違反は提案固有Errorを返す(
    account: Account, ctx: ServiceContext
) -> None:
    session_id = await account.create_session()
    turn_id, _ = await _turn(ctx, account, session_id)
    executor = await _executor(ctx, account, session_id, turn_id)
    campaign = await executor.invoke(
        ToolCall(
            name="propose_campaign",
            stable_key="invalid-campaign-schema",
            arguments={"id": None, "title": "項目不足"},
        )
    )
    post = await executor.invoke(
        ToolCall(
            name="propose_x_post",
            stable_key="invalid-post-schema",
            arguments={"campaign_id": 1, "body": "本文"},
        )
    )
    assert campaign.error is not None
    assert campaign.error.code == "INVALID_CAMPAIGN_PROPOSAL"
    assert post.error is not None
    assert post.error.code == "INVALID_POST_PROPOSAL"


async def test_現在Turn以外のrequestと上限超過を拒否する(
    account: Account,
    ctx: ServiceContext,
    agent: FakeAgentRunner,
) -> None:
    session_id = await account.create_session()
    old_turn_id, old_item_id = await _turn(ctx, account, session_id)
    async with ctx.session_factory() as session, session.begin():
        await TurnRepository(session).finish_turn(
            old_turn_id, status=AgentTurnStatus.COMPLETED, now=ctx.clock.now()
        )
    turn_id, request_id = await _turn(ctx, account, session_id)
    executor = await _executor(ctx, account, session_id, turn_id)
    invalid = await executor.invoke(
        ToolCall(
            name="run_campaign_planner",
            stable_key="old-request",
            arguments={"request_item_id": old_item_id},
        )
    )
    assert invalid.error is not None and invalid.error.code == "INVALID_REQUEST_ITEM"

    ctx.settings.agent_subagent_max_per_turn = 1
    agent.child_output = CampaignPlannerOutput(missing_information=("条件",))
    first = await executor.invoke(
        ToolCall(
            name="run_campaign_planner",
            stable_key="limit-first",
            arguments={"request_item_id": request_id},
        )
    )
    assert first.success is False
    assert first.error is not None and first.error.code == "SUBAGENT_LIMIT_EXCEEDED"


async def test_既存施策提案はDB時刻を注入しcross_companyとarchiveを拒否する(
    account: Account,
    new_account: Any,
    ctx: ServiceContext,
    agent: FakeAgentRunner,
    clock: FixedClock,
) -> None:
    session_id = await account.create_session()
    campaign_id = await account.create_campaign(session_id)
    turn_id, request_id = await _turn(ctx, account, session_id)
    proposal = _campaign_proposal(campaign_id)
    agent.child_output = CampaignPlannerOutput(proposal=proposal)
    executor = await _executor(ctx, account, session_id, turn_id)
    await executor.invoke(
        ToolCall(
            name="run_campaign_planner",
            stable_key="existing-source",
            arguments={"request_item_id": request_id},
        )
    )
    result = await executor.invoke(
        ToolCall(
            name="propose_campaign",
            stable_key="existing-proposal",
            arguments=proposal.model_dump(mode="json"),
        )
    )
    async with ctx.session_factory() as session:
        updated_at = await session.scalar(
            select(Campaign.updated_at).where(Campaign.id == campaign_id)
        )
    assert result.success is True and result.data is not None
    assert updated_at is not None
    assert result.data["expected_updated_at"] == format_utc(updated_at)

    await archive_campaign(campaign_id, clock.now())
    archived = await executor.invoke(
        ToolCall(
            name="propose_campaign",
            stable_key="archived-proposal",
            arguments=proposal.model_dump(mode="json"),
        )
    )
    assert archived.error is not None and archived.error.code == "CAMPAIGN_ARCHIVED"

    other = await new_account()
    other_session = await other.create_session()
    other_campaign = await other.create_campaign(other_session)
    cross_proposal = _campaign_proposal(other_campaign)
    agent.child_output = CampaignPlannerOutput(proposal=cross_proposal)
    cross_run = await executor.invoke(
        ToolCall(
            name="run_campaign_planner",
            stable_key="cross-source",
            arguments={"request_item_id": request_id},
        )
    )
    assert cross_run.success is True
    cross = await executor.invoke(
        ToolCall(
            name="propose_campaign",
            stable_key="cross-proposal",
            arguments=cross_proposal.model_dump(mode="json"),
        )
    )
    assert cross.error is not None and cross.error.code == "CAMPAIGN_NOT_FOUND"
