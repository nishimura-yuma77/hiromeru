"""TurnとItemの表示形式への変換（API_DESIGN 5.1）。"""

from typing import Any

from pydantic import ValidationError

from agent_runtime.proposal_tools import ProposeCampaignOutput, ProposeXPostOutput
from core.errors import DEFAULT_MESSAGES, ERROR_SPECS
from domain.constants import SECURITY_NOTICES_LIMIT
from domain.enums import AgentItemType, AgentTurnStatus
from models import AgentItem
from repositories.agent import TurnBundle, TurnRepository
from services.context import ServiceContext
from services.views import SecurityNoticeView, TurnErrorView, TurnItemView, TurnView


def _approval_item(item: AgentItem, *, completed: bool) -> tuple[str, dict[str, Any]] | None:
    """`approval` Turnのアイテムを表示形式へ変換する。表示しないアイテムは None。"""
    if item.item_type == AgentItemType.USER_MESSAGE and "action" in item.content:
        return "approval_action", item.content["action"]
    is_result = (
        item.item_type == AgentItemType.ASSISTANT_MESSAGE
        and item.content.get("kind") == "api_result"
    )
    if is_result and completed:
        content = item.content
        return "api_result", {
            "operation": content.get("operation"),
            "success": content.get("success"),
            "error": content.get("error"),
        }
    return None


def _chat_item(
    item: AgentItem,
    *,
    completed: bool,
    tool_names: dict[int, str],
    completed_tool_call_ids: frozenset[int],
) -> tuple[str, dict[str, Any]] | None:
    """`chat` Turnのアイテムを表示形式へ変換する。表示しないアイテムは None。

    成功した終端提案Toolだけを表示用proposalへ投影する。
    """
    if item.item_type == AgentItemType.USER_MESSAGE:
        return "user_message", {"text": item.content.get("text", "")}
    if item.item_type == AgentItemType.ASSISTANT_MESSAGE and completed:
        return "assistant_message", {"text": item.content.get("text", "")}
    related = item.related_tool_call_item_id
    if (
        completed
        and item.item_type == AgentItemType.TOOL_RESULT
        and related is not None
        and related in completed_tool_call_ids
        and item.content.get("success") is True
        and isinstance(item.content.get("data"), dict)
    ):
        definitions = {
            "propose_campaign": ("campaign_proposal", ProposeCampaignOutput),
            "propose_x_post": ("x_post_proposal", ProposeXPostOutput),
        }
        projected = definitions.get(tool_names.get(related, ""))
        if projected is not None:
            try:
                content = projected[1].model_validate(item.content["data"])
            except ValidationError:
                return None
            return projected[0], content.model_dump(mode="json")
    return None


def build_turn_view(bundle: TurnBundle) -> TurnView:
    """Turnと関連データから、5.1の形式のTurnを作る。

    完了していないTurnは、ユーザー入力（approvalでは承認内容）だけを返す。
    `context_status = quarantined` のItemは、取得時点で除外している。
    """
    turn = bundle.turn
    completed = turn.status == AgentTurnStatus.COMPLETED
    items: list[TurnItemView] = []
    tool_names = {
        item.id: name
        for item in bundle.items
        if item.item_type == AgentItemType.TOOL_CALL
        and isinstance((name := item.content.get("name")), str)
    }
    for item in bundle.items:
        converted = (
            _approval_item(item, completed=completed)
            if bundle.is_approval
            else _chat_item(
                item,
                completed=completed,
                tool_names=tool_names,
                completed_tool_call_ids=bundle.completed_tool_call_ids,
            )
        )
        if converted is not None:
            items.append(
                TurnItemView(item.id, item.item_number, converted[0], converted[1], item.created_at)
            )
    error = None
    if turn.status in (AgentTurnStatus.FAILED, AgentTurnStatus.BLOCKED) and turn.error_code:
        code = turn.error_code
        error = TurnErrorView(
            code,
            turn.error_message or DEFAULT_MESSAGES.get(code, DEFAULT_MESSAGES["INTERNAL_ERROR"]),
            ERROR_SPECS.get(code, (500, False))[1],
        )
    notices = [
        SecurityNoticeView(event.event_type.value, event.enforcement.value, event.detected_at)
        for event in bundle.notices[:SECURITY_NOTICES_LIMIT]
    ]
    return TurnView(
        agent_turn_id=turn.id,
        turn_number=turn.turn_number,
        kind="approval" if bundle.is_approval else "chat",
        status=turn.status.value,
        error=error,
        started_at=turn.started_at,
        completed_at=turn.completed_at,
        security_notices=notices,
        items=items,
    )


class TurnViewLoader:
    """Turnを読み込んで表示形式へ変換する。"""

    def __init__(self, ctx: ServiceContext) -> None:
        """サービスの依存を受け取る。"""
        self._ctx = ctx

    async def load(self, session_id: int, turn_id: int) -> TurnView | None:
        """指定SessionのTurnを表示形式で返す。存在しなければ None。"""
        async with self._ctx.session_factory() as session:
            repository = TurnRepository(session)
            turn = await repository.get_turn(session_id, turn_id)
            if turn is None:
                return None
            bundles = await repository.bundles([turn])
        return build_turn_view(bundles[0])
