"""DB.dbml の enum と値を一致させる列挙型。"""

from enum import StrEnum


class PostMetricStatus(StrEnum):
    """投稿計測の状態。"""

    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentType(StrEnum):
    """エージェント種別。"""

    PARENT = "parent"
    CAMPAIGN_PLANNER = "campaign_planner"
    CONTENT_CREATOR = "content_creator"


class AgentItemType(StrEnum):
    """エージェントアイテム種別。"""

    USER_MESSAGE = "user_message"
    ASSISTANT_MESSAGE = "assistant_message"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"


class AgentItemContextStatus(StrEnum):
    """アイテムのコンテキスト状態。"""

    ACTIVE = "active"
    QUARANTINED = "quarantined"


class AgentContextClass(StrEnum):
    """アイテムのコンテキスト分類。"""

    CONVERSATION = "conversation"
    UNTRUSTED_DATA = "untrusted_data"


class AgentContentSource(StrEnum):
    """アイテムの取得元。"""

    USER_INPUT = "user_input"
    USER_DOCUMENT = "user_document"
    AGENT_OUTPUT = "agent_output"
    WEB_CONTENT = "web_content"
    WEB_SEARCH = "web_search"
    DATABASE = "database"
    LONG_TERM_MEMORY = "long_term_memory"
    EXTERNAL_API = "external_api"
    MCP_TOOL = "mcp_tool"
    SYSTEM = "system"


class AgentTurnStatus(StrEnum):
    """ターンの状態。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class ToolExecutionStatus(StrEnum):
    """ツール実行の状態。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class ApiOperation(StrEnum):
    """冪等性制御の対象となるAPI操作。"""

    UPSERT_CAMPAIGN = "upsert_campaign"
    PUBLISH_X_POST = "publish_x_post"


class ApiIdempotencyStatus(StrEnum):
    """API冪等性Requestの処理状態。"""

    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    OUTCOME_UNKNOWN = "outcome_unknown"


class SecurityEventType(StrEnum):
    """セキュリティイベント種別。"""

    PROMPT_INJECTION = "prompt_injection"
    SENSITIVE_DATA = "sensitive_data"
    UNAUTHORIZED_TOOL_CALL = "unauthorized_tool_call"
    UNSAFE_EXTERNAL_ACTION = "unsafe_external_action"


class SecurityDetector(StrEnum):
    """セキュリティイベントの検出主体。"""

    APPLICATION = "application"
    ORCAROUTER_GUARDRAIL = "orcarouter_guardrail"
    ORCAROUTER_FIREWALL = "orcarouter_firewall"


class SecurityEnforcement(StrEnum):
    """セキュリティイベントの制御内容。"""

    OBSERVED = "observed"
    SANITIZED = "sanitized"
    BLOCKED = "blocked"
