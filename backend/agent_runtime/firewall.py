"""OrcaRouter固有形式をアプリケーションから隔離するFirewall境界。"""

from enum import StrEnum
from typing import Any, Protocol

import httpx
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


class OrcaRouterAgentFirewall:
    """OrcaRouter gateway-scoped Firewall。障害・未知判定は常にfail closed。"""

    def __init__(self, *, origin: str, api_key: str, timeout_seconds: float) -> None:
        """接続先と専用credentialを保持する。"""
        self._url = f"{origin.rstrip('/')}/api/v1/firewall/evaluate"
        self._api_key = api_key
        self._timeout = timeout_seconds

    async def inspect(self, request: FirewallRequest) -> FirewallDecision:
        """allow/auditだけを許可し、それ以外を遮断する。"""
        try:
            async with httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client:
                response = await client.post(
                    self._url,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={
                        "tool_name": request.tool_name,
                        "arguments": request.masked_arguments,
                        "request_id": request.stable_key,
                    },
                )
            if response.status_code != 200:
                return FirewallDecision.BLOCK
            body = response.json()
            verdict = body.get("verdict")
            if verdict is None and isinstance(body.get("data"), dict):
                verdict = body["data"].get("verdict")
            return (
                FirewallDecision.ALLOW
                if verdict in {"allow", "audit"}
                else FirewallDecision.BLOCK
            )
        except Exception:  # noqa: BLE001 - Provider詳細を公開せずfail closed
            return FirewallDecision.BLOCK
