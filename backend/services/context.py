"""サービス層が共有する依存（実行Context）。"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_runtime.compactor import ContextCompactor
from agent_runtime.firewall import AgentFirewall
from agent_runtime.guardrail import ToolResultGuardrail
from agent_runtime.runner import AgentRunner
from agent_runtime.tools import ToolRegistry
from clients.embedding import EmbeddingClient
from clients.ga4 import Ga4Client
from clients.x_api import XApiClient
from core.clock import Clock
from core.config import Settings


@dataclass(frozen=True)
class AuthContext:
    """認証済みマーケターのContext。`company_id` はDBから決め、Requestから受け取らない。"""

    marketer_id: int
    company_id: int
    user_id: int
    email: str


@dataclass(frozen=True)
class ServiceContext:
    """サービスが使う依存。時刻・ID・待機は、テストで固定できるよう注入する。"""

    settings: Settings
    session_factory: async_sessionmaker[AsyncSession]
    clock: Clock
    embedding: EmbeddingClient
    x_api: XApiClient
    ga4: Ga4Client
    agent_runner: AgentRunner
    context_compactor: ContextCompactor
    tool_registry: ToolRegistry
    agent_firewall: AgentFirewall
    tool_result_guardrail: ToolResultGuardrail
    sleep: Callable[[float], Awaitable[None]]
    new_uuid: Callable[[], uuid.UUID]
