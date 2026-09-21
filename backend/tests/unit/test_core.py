from datetime import UTC, datetime, timedelta

import pytest

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
    with pytest.raises(ValueError, match="SESSION_SECRET"):
        Settings(vercel_env="production", session_secret="")


def test_設定_署名鍵が短いときと開発用の鍵を本番で使うとき起動に失敗する() -> None:
    with pytest.raises(ValueError, match="32文字"):
        Settings(session_secret="short")
    with pytest.raises(ValueError, match="開発用"):
        Settings(
            vercel_env="preview",
            session_secret="dev-only-insecure-session-secret-change-me",
        )


def test_設定_Origin許可リストは環境ごとに組み立てワイルドカードを使わない() -> None:
    production = Settings(
        vercel_env="production",
        session_secret=SECRET,
        allowed_origins="https://App.example.com/, https://www.example.com",
        vercel_project_production_url="hiromeru.vercel.app",
    )
    preview = Settings(
        vercel_env="preview",
        session_secret=SECRET,
        allowed_origins="https://app.example.com",
        vercel_url="hiromeru-abc.vercel.app",
    )
    development = Settings(session_secret=SECRET)

    assert production.resolved_allowed_origins() == {
        "https://app.example.com",
        "https://www.example.com",
        "https://hiromeru.vercel.app",
    }
    assert preview.resolved_allowed_origins() == {"https://hiromeru-abc.vercel.app"}
    assert development.resolved_allowed_origins() == {"http://localhost:3000"}


def test_設定_Embedding次元数がDBの列と違うとき起動に失敗する() -> None:
    with pytest.raises(ValueError, match="EMBEDDING_DIMENSIONS"):
        Settings(session_secret=SECRET, embedding_dimensions=768)
