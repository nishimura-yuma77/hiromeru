from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr

from core.canonical import request_hash
from core.config import Settings
from core.errors import DEFAULT_MESSAGES, ERROR_SPECS, AppError
from core.masking import mask_json, mask_text
from core.security import (
    csrf_token_matches,
    hash_password,
    issue_csrf_token,
    issue_session_token,
    read_session_token,
    sign_payload,
    verify_password,
    verify_payload,
)

SECRET = "unit-test-secret-unit-test-secret-0123456789"
NOW = datetime(2026, 9, 21, 10, 0, tzinfo=UTC)


def _real_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "auth_cookie_secret": SECRET,
        "cookie_secure": True,
        "database_url": "postgresql://production-pooler/database",
        "embedding_client_mode": "real",
        "x_api_client_mode": "real",
        "ga4_client_mode": "real",
        "web_search_client_mode": "real",
        "web_fetch_client_mode": "real",
        "agent_client_mode": "real",
        "agent_firewall_mode": "real",
        "orcarouter_base_url": "https://router.example.com/v1",
        "orcarouter_api_key": "router-secret",
        "orcarouter_firewall_api_key": "firewall-secret",
        "agent_model": "provider/model",
        "x_api_key": "x-key",
        "x_api_key_secret": "x-key-secret",
        "x_access_token": "x-token",
        "x_access_token_secret": "x-token-secret",
        "ga4_property_id": "123456",
        "ga4_service_account_json": '{"type":"service_account"}',
        "web_search_base_url": "https://search.example.com",
        "web_search_api_key": "search-secret",
    }
    values.update(overrides)
    return Settings.model_validate(values)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("連絡先 taro@example.com まで", "連絡先 [EMAIL] まで"),
        ("電話 03-1234-5678 です", "電話 [PHONE] です"),
        ("携帯 09012345678 です", "携帯 [PHONE] です"),
        ("カード 4111 1111 1111 1111 です", "カード [CARD] です"),
        ("api_key=abcdef1234567890", "api_key=[SECRET]"),
        ("Authorization: Bearer abcdefghijklmnop1234", "Authorization: Bearer [SECRET]"),
        (
            'Authorization: OAuth oauth_consumer_key="key", oauth_token="token"',
            "Authorization: OAuth [SECRET]",
        ),
        ("キー sk-abcdefghijklmnopqrstuvwx です", "キー [SECRET] です"),
    ],
)
def test_マスク_機密情報を置換する(raw: str, expected: str) -> None:
    assert mask_text(raw) == expected


def test_マスク_通常の文章と年月日と価格は変えない() -> None:
    text = "2026年9月21日に980円のキャンペーンを開始します"

    assert mask_text(text) == text


def test_マスク_16進識別子内の連続数字は変えない() -> None:
    identifier = "a123456789012345b12345678901234c"

    assert mask_text(identifier) == identifier


def test_マスク_JSONを再帰的に処理し文字列以外は変えない() -> None:
    value = {"a": ["taro@example.com", 1, None], "b": {"c\x00key": "ok\x00value"}}

    assert mask_json(value) == {
        "a": ["[EMAIL]", 1, None],
        "b": {"c[NUL]key": "ok[NUL]value"},
    }


def test_リクエストハッシュ_キー順と空白の違いでは変わらない() -> None:
    assert request_hash({"a": 1, "b": 2}) == request_hash({"b": 2, "a": 1})
    assert request_hash({"a": 1}) != request_hash({"a": 2})


def test_パスワード_正しいときだけ一致しハッシュがないときも偽になる() -> None:
    hashed = hash_password("secret-pass")

    assert verify_password("secret-pass", hashed)
    assert not verify_password("other", hashed)
    assert not verify_password("secret-pass", None)


def test_署名_改ざんと用途違いは検証に失敗する() -> None:
    token = sign_payload(SECRET, "session", {"m": 1})

    assert verify_payload(SECRET, "session", token) == {"m": 1}
    assert verify_payload(SECRET, "csrf", token) is None
    assert verify_payload("another-secret-another-secret-0123456789", "session", token) is None
    assert verify_payload(SECRET, "session", token[:-2] + "xx") is None
    assert verify_payload(SECRET, "session", "garbage") is None


def test_セッショントークン_アイドル期限は8時間で絶対期限を超えない() -> None:
    token, idle = issue_session_token(SECRET, 1, NOW, NOW)
    assert idle == NOW + timedelta(hours=8)
    assert read_session_token(SECRET, token, NOW + timedelta(hours=7)) is not None
    assert read_session_token(SECRET, token, NOW + timedelta(hours=9)) is None

    late = NOW + timedelta(days=6, hours=23)
    _, capped = issue_session_token(SECRET, 1, NOW, late)
    assert capped == NOW + timedelta(days=7)


def test_CSRFトークン_マーケターに束縛されCookieとHeaderが一致するときだけ通る() -> None:
    token = issue_csrf_token(SECRET, 1)

    assert csrf_token_matches(SECRET, 1, token, token)
    assert not csrf_token_matches(SECRET, 2, token, token)
    assert not csrf_token_matches(SECRET, 1, token, issue_csrf_token(SECRET, 1))
    assert not csrf_token_matches(SECRET, 1, "", "")


def test_エラー定義_全コードにメッセージがありApp_Errorは未登録コードを拒否する() -> None:
    assert set(ERROR_SPECS) == set(DEFAULT_MESSAGES)
    error = AppError("CAMPAIGN_CONFLICT")
    assert (error.status_code, error.retryable) == (409, False)
    with pytest.raises(ValueError, match="UNKNOWN"):
        AppError("UNKNOWN")


def test_エラー_X_POST_FAILEDは新しい承認とkeyで再試行可能() -> None:
    assert AppError("X_POST_FAILED").retryable is True


def test_設定_本番で署名鍵がないとき起動に失敗する() -> None:
    with pytest.raises(ValueError, match="AUTH_COOKIE_SECRET"):
        Settings(vercel_env="production", auth_cookie_secret=SecretStr(""))


def test_設定_署名鍵が短いときと開発用の鍵を本番で使うとき起動に失敗する() -> None:
    with pytest.raises(ValueError, match="32文字"):
        Settings(auth_cookie_secret=SecretStr("short"))
    with pytest.raises(ValueError, match="AUTH_COOKIE_SECRET"):
        Settings(
            vercel_env="preview",
            auth_cookie_secret=SecretStr("dev-only-insecure-session-secret-change-me"),
        )


def test_設定_Origin許可リストは環境ごとに組み立てワイルドカードを使わない() -> None:
    production = _real_settings(
        vercel_env="production",
        cron_secret="cron-secret",
        allowed_origins="https://App.example.com/, https://www.example.com",
        vercel_project_production_url="hiromeru.vercel.app",
    )
    preview = _real_settings(
        vercel_env="preview",
        allowed_origins="https://app.example.com",
        vercel_url="hiromeru-abc.vercel.app",
    )
    development = Settings(auth_cookie_secret=SecretStr(SECRET))

    assert production.resolved_allowed_origins() == {
        "https://app.example.com",
        "https://www.example.com",
        "https://hiromeru.vercel.app",
    }
    assert preview.resolved_allowed_origins() == {"https://hiromeru-abc.vercel.app"}
    assert development.resolved_allowed_origins() == {"http://localhost:3000"}


def test_設定_Embedding次元数がDBの列と違うとき起動に失敗する() -> None:
    with pytest.raises(ValueError, match="EMBEDDING_DIMENSIONS"):
        Settings(auth_cookie_secret=SecretStr(SECRET), embedding_dimensions=768)


def test_設定_AUTH_COOKIE_SECRETだけを署名鍵として読む(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_COOKIE_SECRET", SECRET)
    monkeypatch.setenv("SESSION_SECRET", "legacy-secret-legacy-secret-legacy-secret")

    settings = Settings()

    assert settings.auth_secret() == SECRET


def test_設定_ローカルの空のAUTH_COOKIE_SECRETは開発用既定値を使う(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_COOKIE_SECRET", "")

    settings = Settings()

    assert settings.auth_secret() == "dev-only-insecure-session-secret-change-me"


def test_設定_本番とPreviewでSecure_CookieとClient_Mode明示を必須にする() -> None:
    with pytest.raises(ValueError, match="COOKIE_SECURE"):
        _real_settings(vercel_env="production", cookie_secure=False, cron_secret="cron-secret")
    with pytest.raises(ValueError, match="EMBEDDING_CLIENT_MODE"):
        Settings(
            vercel_env="preview",
            auth_cookie_secret=SecretStr(SECRET),
            cookie_secure=True,
            database_url=SecretStr("postgresql://preview/database"),
        )
    deployed_fake = Settings(
        vercel_env="preview",
        auth_cookie_secret=SecretStr(SECRET),
        cookie_secure=True,
        database_url=SecretStr("postgresql://preview/database"),
        embedding_client_mode="fake",
        x_api_client_mode="fake",
        ga4_client_mode="fake",
        web_search_client_mode="fake",
        web_fetch_client_mode="fake",
        agent_client_mode="fake",
        agent_firewall_mode="fake",
    )

    assert deployed_fake.agent_firewall_mode == "fake"


def test_設定_デプロイ環境のClient_Modeは環境変数から明示できる(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "EMBEDDING_CLIENT_MODE",
        "X_API_CLIENT_MODE",
        "GA4_CLIENT_MODE",
        "WEB_SEARCH_CLIENT_MODE",
        "WEB_FETCH_CLIENT_MODE",
        "AGENT_CLIENT_MODE",
        "AGENT_FIREWALL_MODE",
    ):
        monkeypatch.setenv(name, "fake")

    settings = Settings(
        vercel_env="preview",
        auth_cookie_secret=SecretStr(SECRET),
        cookie_secure=True,
        database_url=SecretStr("postgresql://preview/database"),
    )

    assert settings.embedding_client_mode == "fake"
    assert settings.agent_firewall_mode == "fake"


def test_設定_各実Clientだけ固有Credentialを必須にしFakeでは省略できる() -> None:
    fake = Settings(auth_cookie_secret=SecretStr(SECRET))
    with pytest.raises(ValueError, match="ORCAROUTER_API_KEY"):
        Settings(
            auth_cookie_secret=SecretStr(SECRET),
            embedding_client_mode="real",
            orcarouter_base_url="https://router.example.com/v1",
            orcarouter_api_key=SecretStr(""),
        )
    with pytest.raises(ValueError, match="X_API_KEY"):
        Settings(
            auth_cookie_secret=SecretStr(SECRET),
            x_api_client_mode="real",
            x_api_key=SecretStr(""),
        )
    with pytest.raises(ValueError, match="GA4_PROPERTY_ID"):
        Settings(
            auth_cookie_secret=SecretStr(SECRET),
            ga4_client_mode="real",
            ga4_property_id="",
        )
    with pytest.raises(ValueError, match="WEB_SEARCH_API_KEY"):
        Settings(
            auth_cookie_secret=SecretStr(SECRET),
            web_search_client_mode="real",
            web_search_base_url="https://search.example.com",
            web_search_api_key=SecretStr(""),
        )

    assert fake.embedding_client_mode == "fake"
    assert fake.x_api_client_mode == "fake"
    assert fake.ga4_client_mode == "fake"
    assert fake.web_search_client_mode == "fake"
    assert fake.web_fetch_client_mode == "fake"


def test_設定_実Agentは他ClientがFakeでもOrcaRouter設定だけで起動できる() -> None:
    settings = Settings(
        auth_cookie_secret=SecretStr(SECRET),
        agent_client_mode="real",
        orcarouter_base_url="https://router.example.com/v1",
        orcarouter_api_key=SecretStr("router-secret"),
        agent_model="provider/model",
    )

    assert settings.embedding_client_mode == "fake"
    assert settings.agent_client_mode == "real"
    assert settings.agent_firewall_mode == "fake"


def test_設定_実AgentではAgent用Credentialを必須にする() -> None:
    with pytest.raises(ValueError, match="AGENT_MODEL"):
        Settings(
            auth_cookie_secret=SecretStr(SECRET),
            agent_client_mode="real",
            orcarouter_base_url="https://router.example.com/v1",
            orcarouter_api_key=SecretStr("router-secret"),
            agent_model="",
        )


def test_設定_実Firewallでは専用Credentialを必須にする() -> None:
    with pytest.raises(ValueError, match="ORCAROUTER_FIREWALL_API_KEY"):
        Settings(
            auth_cookie_secret=SecretStr(SECRET),
            agent_firewall_mode="real",
            orcarouter_base_url="https://router.example.com/v1",
            orcarouter_firewall_api_key=SecretStr(""),
        )


def test_設定_空白だけのSecretと実Client設定を拒否する() -> None:
    with pytest.raises(ValueError, match="AUTH_COOKIE_SECRET"):
        Settings(auth_cookie_secret=SecretStr(" " * 32))
    with pytest.raises(ValueError, match="ORCAROUTER_API_KEY"):
        _real_settings(orcarouter_api_key=" ")
    with pytest.raises(ValueError, match="CRON_SECRET"):
        _real_settings(vercel_env="production", cron_secret=" ")


def test_設定_本番とPreviewではDatabase_URLを明示設定する() -> None:
    with pytest.raises(ValueError, match="DATABASE_URL"):
        _real_settings(
            vercel_env="preview",
            database_url="postgresql+psycopg://app:app@localhost:5432/app",
        )


def test_設定_ProductionだけCron_Secretを必須にする() -> None:
    with pytest.raises(ValueError, match="CRON_SECRET"):
        _real_settings(vercel_env="production")

    assert _real_settings(vercel_env="preview").cron_secret.get_secret_value() == ""


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"cron_metric_batch_size": 0}, "CRON_METRIC_BATCH_SIZE"),
        ({"cron_metric_max_items": 19}, "CRON_METRIC_MAX_ITEMS"),
        ({"cron_metric_max_attempts": 0}, "CRON_METRIC_MAX_ATTEMPTS"),
        ({"cron_memory_batch_size": 0}, "CRON_MEMORY_BATCH_SIZE"),
        ({"cron_memory_max_items": 19}, "CRON_MEMORY_MAX_ITEMS"),
        ({"cron_memory_max_attempts": 0}, "CRON_MEMORY_MAX_ATTEMPTS"),
        ({"lease_seconds": 300}, "LEASE_SECONDS"),
        ({"request_timeout_seconds": 0}, "REQUEST_TIMEOUT_SECONDS"),
        ({"request_timeout_seconds": 300.1}, "REQUEST_TIMEOUT_SECONDS"),
        ({"subagent_llm_timeout_seconds": 0}, "SUBAGENT_LLM_TIMEOUT_SECONDS"),
        ({"subagent_llm_timeout_seconds": 201}, "SUBAGENT_LLM_TIMEOUT_SECONDS"),
        ({"subagent_llm_max_output_tokens": 0}, "Agent step/output token"),
        (
            {"agent_context_compaction_threshold_bytes": 0},
            "AGENT_CONTEXT_COMPACTION_THRESHOLD_BYTES",
        ),
        ({"agent_context_hard_limit_bytes": 0}, "AGENT_CONTEXT_HARD_LIMIT_BYTES"),
        (
            {
                "agent_context_compaction_threshold_bytes": 100,
                "agent_context_hard_limit_bytes": 100,
            },
            "AGENT_CONTEXT_COMPACTION_THRESHOLD_BYTES",
        ),
    ],
)
def test_設定_Cron上限とLease境界を検証する(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        Settings.model_validate({"auth_cookie_secret": SECRET, **overrides})


def test_設定_Secret値を文字列表現とValidation_Errorへ出さない() -> None:
    sentinel = "do-not-leak-this-secret-value"
    settings = Settings(
        auth_cookie_secret=SecretStr(SECRET),
        orcarouter_api_key=SecretStr(sentinel),
        x_api_key_secret=SecretStr(sentinel),
        ga4_service_account_json=SecretStr(sentinel),
        cron_secret=SecretStr(sentinel),
    )

    assert sentinel not in repr(settings)
    assert sentinel not in str(settings)
    assert sentinel not in settings.model_dump_json()
    with pytest.raises(ValueError) as info:
        Settings(auth_cookie_secret=SecretStr(sentinel), lease_seconds=300)
    assert sentinel not in str(info.value)


def test_設定_MigrationはUnpooled_URLを必須にしてFallbackしない(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL_UNPOOLED", raising=False)
    settings = Settings.model_validate(
        {"auth_cookie_secret": SECRET, "database_url": "postgresql://pooled"}
    )
    with pytest.raises(ValueError, match="DATABASE_URL_UNPOOLED"):
        settings.migration_database_url()

    direct = Settings.model_validate(
        {
            "auth_cookie_secret": SECRET,
            "database_url": "postgresql://pooled",
            "database_url_unpooled": "postgresql://direct",
        }
    )
    assert direct.application_database_url() == "postgresql://pooled"
    assert direct.migration_database_url() == "postgresql://direct"

    blank = Settings.model_validate(
        {
            "auth_cookie_secret": SECRET,
            "database_url_unpooled": " ",
        }
    )
    with pytest.raises(ValueError, match="DATABASE_URL_UNPOOLED"):
        blank.migration_database_url()
