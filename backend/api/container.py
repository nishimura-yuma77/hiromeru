"""実行Contextの組み立て。"""

import asyncio
import uuid

from fastapi import Request

from agent_runtime.business_tools import ToolHandlerDependencies, build_default_tool_registry
from agent_runtime.compactor import StubContextCompactor
from agent_runtime.firewall import DenyAllAgentFirewall
from agent_runtime.guardrail import DenyAllToolResultGuardrail, FakeToolResultGuardrail
from agent_runtime.runner import StubAgentRunner
from agent_runtime.web_tools import WebToolDependencies, register_web_tools
from clients.embedding import OrcaRouterEmbeddingClient
from clients.fakes import FakeEmbeddingClient, FakeXApiClient
from clients.web_fetch import HttpxPinnedTransport, SafeWebFetcher, SystemResolver
from clients.web_search import FakeWebSearchProvider, HttpWebSearchProvider
from clients.x_api import HttpXApiClient
from core.clock import SystemClock
from core.config import Settings, get_settings
from repositories.database import SessionLocal
from services.context import ServiceContext


def build_default_context(settings: Settings | None = None) -> ServiceContext:
    """本番・開発用の実行Contextを作る。"""
    resolved = settings or get_settings()
    if resolved.external_client_mode == "fake":
        embedding = FakeEmbeddingClient(resolved.embedding_dimensions)
        x_api = FakeXApiClient()
        web_search = FakeWebSearchProvider()
        guardrail = FakeToolResultGuardrail()
    else:
        embedding = OrcaRouterEmbeddingClient(
            base_url=resolved.orcarouter_base_url,
            api_key=resolved.orcarouter_api_key.get_secret_value(),
            model=resolved.embedding_model,
            dimensions=resolved.embedding_dimensions,
            timeout_seconds=resolved.embedding_timeout_seconds,
        )
        x_api = HttpXApiClient(
            base_url=resolved.x_api_base_url,
            api_key=resolved.x_api_key.get_secret_value(),
            api_key_secret=resolved.x_api_key_secret.get_secret_value(),
            access_token=resolved.x_access_token.get_secret_value(),
            access_token_secret=resolved.x_access_token_secret.get_secret_value(),
            timeout_seconds=resolved.x_api_timeout_seconds,
        )
        web_search = HttpWebSearchProvider(
            base_url=resolved.web_search_base_url,
            api_key=resolved.web_search_api_key.get_secret_value(),
            timeout_seconds=resolved.web_search_timeout_seconds,
        )
        guardrail = DenyAllToolResultGuardrail()
    clock = SystemClock()
    registry = build_default_tool_registry(
        ToolHandlerDependencies(resolved, SessionLocal, embedding, clock)
    )
    register_web_tools(
        registry,
        WebToolDependencies(
            SessionLocal,
            web_search,
            SafeWebFetcher(
                resolver=SystemResolver(),
                transport=HttpxPinnedTransport(resolved.web_fetch_timeout_seconds),
                max_bytes=resolved.web_fetch_max_bytes,
                max_redirects=resolved.web_fetch_max_redirects,
            ),
            uuid.uuid4,
        ),
    )
    return ServiceContext(
        settings=resolved,
        session_factory=SessionLocal,
        clock=clock,
        embedding=embedding,
        x_api=x_api,
        agent_runner=StubAgentRunner(),
        context_compactor=StubContextCompactor(),
        tool_registry=registry,
        agent_firewall=DenyAllAgentFirewall(),
        tool_result_guardrail=guardrail,
        sleep=asyncio.sleep,
        new_uuid=uuid.uuid4,
    )


def get_service_context(request: Request) -> ServiceContext:
    """アプリケーションに設定された実行Contextを返す。未設定なら既定を作る。"""
    context = getattr(request.app.state, "context", None)
    if context is None:
        # モジュールレベルにRequest固有の状態は持たない。ここで保持するのは設定と接続先だけ。
        context = build_default_context()
        request.app.state.context = context
    return context  # type: ignore[no-any-return]
