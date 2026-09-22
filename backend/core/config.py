"""アプリケーション設定。環境変数から読み込み、起動時に検証する（BE_STD 10章）。"""

from functools import lru_cache
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from domain.constants import EMBEDDING_DIMENSIONS

# 開発・テスト専用の署名鍵。本番・プレビューでは使用を禁止する。
_DEV_SESSION_SECRET = "dev-only-insecure-session-secret-change-me"
_MIN_SECRET_LENGTH = 32
_DEV_ORIGIN = "http://localhost:3000"
_MAX_DURATION_SECONDS = 300
_DEV_DATABASE_URL = "postgresql+psycopg://app:app@localhost:5432/app"

type ExternalClientMode = Literal["real", "fake"]


class Settings(BaseSettings):
    """環境変数から読み込む型付き設定。"""

    database_url: SecretStr = SecretStr(_DEV_DATABASE_URL)
    database_url_unpooled: SecretStr | None = None

    # 認証Cookie・CSRFトークンの署名鍵（API_DESIGN 2.8）。
    auth_cookie_secret: SecretStr = SecretStr(_DEV_SESSION_SECRET)
    cookie_secure: bool = True

    # Originの許可リスト（BE_STD 17.1）。カンマ区切り。
    allowed_origins: str = ""
    vercel_env: str | None = None
    vercel_url: str | None = None
    vercel_branch_url: str | None = None
    vercel_project_production_url: str | None = None

    # 外部API。開発・テストだけFakeを許可する。
    external_client_mode: ExternalClientMode = "fake"

    # 埋め込み（BE_STD 13章）。モデル名と次元数は設定値とする。
    embedding_model: str = "openai/text-embedding-3-small"
    embedding_dimensions: int = EMBEDDING_DIMENSIONS
    orcarouter_base_url: str = ""
    orcarouter_api_key: SecretStr = SecretStr("")
    embedding_timeout_seconds: float = 30.0

    # X API。OAuth 1.0a User Context用の4 Credential。
    x_api_base_url: str = "https://api.x.com"
    x_api_key: SecretStr = SecretStr("")
    x_api_key_secret: SecretStr = SecretStr("")
    x_access_token: SecretStr = SecretStr("")
    x_access_token_secret: SecretStr = SecretStr("")
    x_api_timeout_seconds: float = 30.0

    # GA4 Data API。Client本体はIssue #33で実装する。
    ga4_property_id: str = ""
    ga4_service_account_json: SecretStr = SecretStr("")

    # Vercel Cron。Endpoint本体はIssue #35で実装する。
    cron_secret: SecretStr = SecretStr("")
    cron_metric_batch_size: int = 20
    cron_metric_max_items: int = 100
    cron_metric_max_attempts: int = 3
    cron_memory_batch_size: int = 20
    cron_memory_max_items: int = 100
    cron_memory_max_attempts: int = 3

    # Agent Turn（API_DESIGN 5.3、AGENT_DESIGN「Turnの上限」「中断されたTurnの復旧」）。
    request_timeout_seconds: float = 300.0
    message_max_length: int = 4000
    turn_time_limit_seconds: float = 200.0
    stale_turn_seconds: float = 330.0
    tool_max_attempts: int = 3
    tool_retry_backoff_seconds: float = 0.25
    tool_attempt_timeout_seconds: float = 30.0
    tool_search_limit: int = 20
    tool_session_item_limit: int = 20
    tool_session_output_max_bytes: int = 64_000
    tool_memory_content_max_length: int = 4_000
    tool_memory_relation_limit: int = 20
    # Context量は決定論的にserializeしたJSONのUTF-8 byte数で測る。
    agent_context_compaction_threshold_bytes: int = 64_000
    agent_context_hard_limit_bytes: int = 128_000
    # API_DESIGN 2.3: Lease は maxDuration（300秒）より長くする。
    lease_seconds: float = 330.0

    log_level: str = "INFO"
    log_json: bool = True

    model_config = SettingsConfigDict(
        env_file=".env", env_ignore_empty=True, extra="ignore", hide_input_in_errors=True
    )

    @model_validator(mode="after")
    def _validate(self) -> Self:
        """環境別のSecret、Client Mode、実行上限を検証する。"""
        is_deployed = self.vercel_env in ("production", "preview")
        self._validate_environment(is_deployed)
        self._validate_external_clients()
        self._validate_cron_limits()
        self._validate_runtime_limits()
        if self.embedding_dimensions != EMBEDDING_DIMENSIONS:
            # DB の列は vector(1536) に固定のため、次元数を変えるには移行が必要（BE_STD 13章）。
            raise ValueError("EMBEDDING_DIMENSIONS がDBの列の次元数と一致しません")
        return self

    def _validate_environment(self, is_deployed: bool) -> None:
        """認証・Cookie・Deploy環境固有の必須設定を検証する。"""
        auth_secret = self.auth_cookie_secret.get_secret_value()
        if len(auth_secret.strip()) < _MIN_SECRET_LENGTH:
            raise ValueError("AUTH_COOKIE_SECRET は32文字以上にしてください")
        if is_deployed and auth_secret == _DEV_SESSION_SECRET:
            raise ValueError("AUTH_COOKIE_SECRET を本番・プレビュー用に設定してください")
        if is_deployed and not self.cookie_secure:
            raise ValueError("本番・プレビューでは COOKIE_SECURE=true が必須です")
        if is_deployed and self.external_client_mode != "real":
            raise ValueError("本番・プレビューでは EXTERNAL_CLIENT_MODE=real が必須です")
        if is_deployed and self.application_database_url().strip() == _DEV_DATABASE_URL:
            raise ValueError("本番・プレビューでは DATABASE_URL が必須です")
        if self.vercel_env == "production" and not self.cron_secret.get_secret_value().strip():
            raise ValueError("Productionでは CRON_SECRET が必須です")

    def _validate_external_clients(self) -> None:
        """実Client Modeで必要な接続設定を検証する。"""
        if self.external_client_mode == "real":
            required = {
                "ORCAROUTER_BASE_URL": self.orcarouter_base_url,
                "ORCAROUTER_API_KEY": self.orcarouter_api_key.get_secret_value(),
                "X_API_KEY": self.x_api_key.get_secret_value(),
                "X_API_KEY_SECRET": self.x_api_key_secret.get_secret_value(),
                "X_ACCESS_TOKEN": self.x_access_token.get_secret_value(),
                "X_ACCESS_TOKEN_SECRET": self.x_access_token_secret.get_secret_value(),
                "GA4_PROPERTY_ID": self.ga4_property_id,
                "GA4_SERVICE_ACCOUNT_JSON": self.ga4_service_account_json.get_secret_value(),
            }
            missing = [name for name, value in required.items() if not value.strip()]
            if missing:
                raise ValueError(f"実Clientに必要な設定がありません: {', '.join(missing)}")

    def _validate_cron_limits(self) -> None:
        """Cronの件数・試行回数とLeaseの境界を検証する。"""
        limits = {
            "CRON_METRIC_BATCH_SIZE": self.cron_metric_batch_size,
            "CRON_METRIC_MAX_ITEMS": self.cron_metric_max_items,
            "CRON_METRIC_MAX_ATTEMPTS": self.cron_metric_max_attempts,
            "CRON_MEMORY_BATCH_SIZE": self.cron_memory_batch_size,
            "CRON_MEMORY_MAX_ITEMS": self.cron_memory_max_items,
            "CRON_MEMORY_MAX_ATTEMPTS": self.cron_memory_max_attempts,
        }
        invalid = [name for name, value in limits.items() if value <= 0]
        if invalid:
            raise ValueError(f"正の整数を指定してください: {', '.join(invalid)}")
        if self.cron_metric_max_items < self.cron_metric_batch_size:
            raise ValueError("CRON_METRIC_MAX_ITEMS は BATCH_SIZE 以上にしてください")
        if self.cron_memory_max_items < self.cron_memory_batch_size:
            raise ValueError("CRON_MEMORY_MAX_ITEMS は BATCH_SIZE 以上にしてください")
        if self.lease_seconds <= _MAX_DURATION_SECONDS:
            raise ValueError("LEASE_SECONDS は300秒より長くしてください")

    def _validate_runtime_limits(self) -> None:
        """Request全体のTimeoutをVercelの実行上限内に保つ。"""
        if not 0 < self.request_timeout_seconds <= _MAX_DURATION_SECONDS:
            raise ValueError("REQUEST_TIMEOUT_SECONDS は0秒より大きく300秒以下にしてください")
        if not 0 < self.turn_time_limit_seconds < self.request_timeout_seconds:
            raise ValueError(
                "TURN_TIME_LIMIT_SECONDS は0秒より大きくREQUEST_TIMEOUT_SECONDS未満にしてください"
            )
        if self.stale_turn_seconds <= self.turn_time_limit_seconds:
            raise ValueError("STALE_TURN_SECONDS はTURN_TIME_LIMIT_SECONDSより大きくしてください")
        if self.tool_max_attempts <= 0:
            raise ValueError("TOOL_MAX_ATTEMPTS は正の整数にしてください")
        if self.tool_retry_backoff_seconds <= 0:
            raise ValueError("TOOL_RETRY_BACKOFF_SECONDS は正数にしてください")
        if not 0 < self.tool_attempt_timeout_seconds <= self.turn_time_limit_seconds:
            raise ValueError(
                "TOOL_ATTEMPT_TIMEOUT_SECONDS は0秒より大きく"
                "TURN_TIME_LIMIT_SECONDS以下にしてください"
            )
        if self.agent_context_compaction_threshold_bytes <= 0:
            raise ValueError("AGENT_CONTEXT_COMPACTION_THRESHOLD_BYTES は正数にしてください")
        if self.agent_context_hard_limit_bytes <= 0:
            raise ValueError("AGENT_CONTEXT_HARD_LIMIT_BYTES は正数にしてください")
        if self.agent_context_compaction_threshold_bytes >= self.agent_context_hard_limit_bytes:
            raise ValueError(
                "AGENT_CONTEXT_COMPACTION_THRESHOLD_BYTES は"
                " AGENT_CONTEXT_HARD_LIMIT_BYTES 未満にしてください"
            )
        integer_limits = {
            "TOOL_SEARCH_LIMIT": (self.tool_search_limit, 100),
            "TOOL_SESSION_ITEM_LIMIT": (self.tool_session_item_limit, 100),
            "TOOL_SESSION_OUTPUT_MAX_BYTES": (self.tool_session_output_max_bytes, 1_000_000),
            "TOOL_MEMORY_CONTENT_MAX_LENGTH": (self.tool_memory_content_max_length, 20_000),
            "TOOL_MEMORY_RELATION_LIMIT": (self.tool_memory_relation_limit, 100),
        }
        invalid = [
            name for name, (value, maximum) in integer_limits.items() if not 0 < value <= maximum
        ]
        if invalid:
            raise ValueError(f"Tool上限は正数かつ合理的な範囲にしてください: {', '.join(invalid)}")

    def auth_secret(self) -> str:
        """認証Tokenの署名境界でだけ署名鍵を平文として返す。"""
        return self.auth_cookie_secret.get_secret_value()

    def application_database_url(self) -> str:
        """Application用のDB接続URLを返す。"""
        return self.database_url.get_secret_value()

    def migration_database_url(self) -> str:
        """Migration用のDirect接続URLを返す。Fallbackは許可しない。"""
        if self.database_url_unpooled is None:
            raise ValueError("DATABASE_URL_UNPOOLED が未設定です")
        value = self.database_url_unpooled.get_secret_value()
        if not value.strip():
            raise ValueError("DATABASE_URL_UNPOOLED が未設定です")
        return value

    @staticmethod
    def sqlalchemy_url(url: str) -> str:
        """接続文字列を psycopg（v3）のドライバ指定へ正規化する。"""
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+psycopg://", 1)
        return url

    def resolved_allowed_origins(self) -> frozenset[str]:
        """環境ごとのOrigin許可リストを組み立てる。ワイルドカードは使わない。"""
        origins: set[str] = set()
        configured = [item.strip() for item in self.allowed_origins.split(",") if item.strip()]
        if self.vercel_env == "production":
            origins.update(configured)
            if self.vercel_project_production_url:
                origins.add(f"https://{self.vercel_project_production_url}")
        elif self.vercel_env == "preview":
            # 本番のオリジンは許可しない。そのデプロイ自身のURLだけを許可する。
            for host in (self.vercel_url, self.vercel_branch_url):
                if host:
                    origins.add(f"https://{host}")
        else:
            origins.update(configured or [_DEV_ORIGIN])
        return frozenset(_normalize_origin(origin) for origin in origins)


def _normalize_origin(origin: str) -> str:
    """末尾のスラッシュなどを除き、`scheme://host[:port]` の小文字に揃える。"""
    parts = urlsplit(origin.strip())
    return f"{parts.scheme}://{parts.netloc}".lower()


def normalize_origin(origin: str) -> str:
    """Origin または Referer から `scheme://host[:port]` を取り出す。"""
    return _normalize_origin(origin)


@lru_cache
def get_settings() -> Settings:
    """設定を1度だけ読み込む。"""
    return Settings()
