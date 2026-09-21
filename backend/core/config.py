"""アプリケーション設定。環境変数から読み込み、起動時に検証する（BE_STD 10章）。"""

from functools import lru_cache
from typing import Self
from urllib.parse import urlsplit

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from domain.constants import EMBEDDING_DIMENSIONS

# 開発・テスト専用の署名鍵。本番・プレビューでは使用を禁止する。
_DEV_SESSION_SECRET = "dev-only-insecure-session-secret-change-me"
_MIN_SECRET_LENGTH = 32
_DEV_ORIGIN = "http://localhost:3000"


class Settings(BaseSettings):
    """環境変数から読み込む型付き設定。"""

    database_url: str = "postgresql+psycopg://app:app@localhost:5432/app"
    database_url_unpooled: str | None = None

    # 認証Cookie・CSRFトークンの署名鍵（API_DESIGN 2.8）。
    session_secret: str = ""
    cookie_secure: bool = True

    # Originの許可リスト（BE_STD 17.1）。カンマ区切り。
    allowed_origins: str = ""
    vercel_env: str | None = None
    vercel_url: str | None = None
    vercel_branch_url: str | None = None
    vercel_project_production_url: str | None = None

    # 埋め込み（BE_STD 13章）。モデル名と次元数は設定値とする。
    embedding_model: str = "openai/text-embedding-3-small"
    embedding_dimensions: int = EMBEDDING_DIMENSIONS
    orcarouter_base_url: str = ""
    orcarouter_api_key: str = ""
    embedding_timeout_seconds: float = 30.0

    # X API。投稿はユーザーコンテキストのアクセストークンで行う。
    x_api_base_url: str = "https://api.x.com"
    x_access_token: str = ""
    x_api_timeout_seconds: float = 30.0

    # Agent Turn（API_DESIGN 5.3、AGENT_DESIGN「Turnの上限」「中断されたTurnの復旧」）。
    message_max_length: int = 4000
    turn_time_limit_seconds: float = 200.0
    stale_turn_seconds: float = 330.0
    # API_DESIGN 2.3: Lease は maxDuration（300秒）より長くする。
    lease_seconds: float = 330.0

    log_level: str = "INFO"
    log_json: bool = True

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def _validate(self) -> Self:
        """署名鍵と埋め込み次元数を検証する。足りなければ起動を失敗させる。"""
        is_deployed = self.vercel_env in ("production", "preview")
        if not self.session_secret:
            if is_deployed:
                raise ValueError("SESSION_SECRET が未設定です")
            self.session_secret = _DEV_SESSION_SECRET
        elif len(self.session_secret) < _MIN_SECRET_LENGTH:
            raise ValueError("SESSION_SECRET は32文字以上にしてください")
        if is_deployed and self.session_secret == _DEV_SESSION_SECRET:
            raise ValueError("開発用の SESSION_SECRET は本番・プレビューで使用できません")
        if self.embedding_dimensions != EMBEDDING_DIMENSIONS:
            # DB の列は vector(1536) に固定のため、次元数を変えるには移行が必要（BE_STD 13章）。
            raise ValueError("EMBEDDING_DIMENSIONS がDBの列の次元数と一致しません")
        return self

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
