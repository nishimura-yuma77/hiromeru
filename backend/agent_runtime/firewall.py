"""OrcaRouter固有形式をアプリケーションから隔離するFirewall境界。"""

from enum import StrEnum
from typing import Any, Protocol

from pydantic import Field

from agent_runtime.tools import StrictToolModel, ToolProvenanceRef
from domain.enums import AgentType


class FirewallDecision(StrEnum):
    """Agent Firewallの安全な判定。"""

    ALLOW = "allow"
    BLOCK = "block"


class FirewallRequest(StrictToolModel):
    """Firewallへ渡す最小データ。Tenant値はTrusted Context側に置く。"""

    tool_name: str
    masked_arguments: dict[str, Any]
    agent_type: AgentType
    provenance: tuple[ToolProvenanceRef, ...]
    stable_key: str = Field(min_length=1, max_length=200)


class AgentFirewall(Protocol):
    """OrcaRouter Agent Firewallの抽象境界。"""

    async def inspect(self, request: FirewallRequest) -> FirewallDecision:
        """検査結果だけを返す。外部のreasonやrule matchは公開しない。"""
        ...


class DenyAllAgentFirewall:
    """実Firewallが設定されていない環境でTool実行をfail closedにする。"""

    async def inspect(self, request: FirewallRequest) -> FirewallDecision:
        """登録済みToolであっても外部検査なしでは許可しない。"""
        del request
        return FirewallDecision.BLOCK


class FakeAgentFirewall:
    """テスト用Firewall。"""

    def __init__(self, decision: FirewallDecision = FirewallDecision.ALLOW) -> None:
        """初期判定を設定する。"""
        self.decision = decision
        self.requests: list[FirewallRequest] = []

    async def inspect(self, request: FirewallRequest) -> FirewallDecision:
        """Requestを記録して設定済み判定を返す。"""
        self.requests.append(request)
        return self.decision
