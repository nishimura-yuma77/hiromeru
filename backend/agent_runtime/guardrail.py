"""未信頼Tool Resultを検査するGuardrail境界。"""

from enum import StrEnum
from typing import Any, Protocol

from agent_runtime.tools import StrictToolModel


class GuardrailDecision(StrEnum):
    """外部Guardrailの安全な判定。"""

    ALLOW = "allow"
    BLOCK = "block"


class GuardrailRequest(StrictToolModel):
    """内容以外を固定分類し、検査対象だけを明示するRequest。"""

    tool_name: str
    content: dict[str, Any]


class ToolResultGuardrail(Protocol):
    """未信頼Tool Resultの検査境界。"""

    async def inspect(self, request: GuardrailRequest) -> GuardrailDecision:
        """Resultを許可または遮断する。"""
        ...


class DenyAllToolResultGuardrail:
    """実Guardrail未設定時に未信頼Resultをfail closedにする。"""

    async def inspect(self, request: GuardrailRequest) -> GuardrailDecision:
        """常に遮断する。"""
        del request
        return GuardrailDecision.BLOCK


class FakeToolResultGuardrail:
    """テスト・fake mode用の記録可能なGuardrail。"""

    def __init__(self, decision: GuardrailDecision = GuardrailDecision.ALLOW) -> None:
        """初期判定を設定する。"""
        self.decision = decision
        self.requests: list[GuardrailRequest] = []

    async def inspect(self, request: GuardrailRequest) -> GuardrailDecision:
        """Requestを記録して設定済み判定を返す。"""
        self.requests.append(request)
        return self.decision
