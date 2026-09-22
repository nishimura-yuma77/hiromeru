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
        "external_client_mode": "real",
        "orcarouter_base_url": "https://router.example.com/v1",
        "orcarouter_api_key": "router-secret",
        "x_api_key": "x-key",
        "x_api_key_secret": "x-key-secret",
        "x_access_token": "x-token",
        "x_access_token_secret": "x-token-secret",
        "ga4_property_id": "123456",
        "ga4_service_account_json": '{"type":"service_account"}',
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
        ("キー sk-abcdefghijklmnopqrstuvwx です", "キー [SECRET] です"),
    ],
)
def test_マスク_機密情報を置換する(raw: str, expected: str) -> None:
    assert mask_text(raw) == expected


def test_マスク_通常の文章と年月日と価格は変えない() -> None:
    text = "2026年9月21日に980円のキャンペーンを開始します"

    assert mask_text(text) == text


def test_マスク_JSONを再帰的に処理し文字列以外は変えない() -> None:
    value = {"a": ["taro@example.com", 1, None], "b": {"c": "ok"}}

    assert mask_json(value) == {"a": ["[EMAIL]", 1, None], "b": {"c": "ok"}}


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


def test_エラー_X_POST_FAILEDは429のときだけ再試行可能を指定できる() -> None:
    assert AppError("X_POST_FAILED").retryable is False
    assert AppError("X_POST_FAILED", retryable=True).retryable is True


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


def test_設定_本番とPreviewでSecure_Cookieと実Clientを必須にする() -> None:
    with pytest.raises(ValueError, match="COOKIE_SECURE"):
        _real_settings(vercel_env="production", cookie_secure=False, cron_secret="cron-secret")
    with pytest.raises(ValueError, match="EXTERNAL_CLIENT_MODE"):
        Settings(
            vercel_env="preview",
            auth_cookie_secret=SecretStr(SECRET),
            cookie_secure=True,
        )


def test_設定_実ClientではCredentialをすべて必須にしFakeでは省略できる() -> None:
    fake = Settings(auth_cookie_secret=SecretStr(SECRET), external_client_mode="fake")
    with pytest.raises(ValueError, match="GA4_PROPERTY_ID"):
        _real_settings(ga4_property_id="")

    assert fake.external_client_mode == "fake"


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
