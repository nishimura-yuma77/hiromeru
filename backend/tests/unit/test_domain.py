from datetime import UTC, datetime, timedelta, timezone

import pytest

from domain.campaign_rules import CampaignContent, campaign_field_errors
from domain.cursor import CursorError, decode_cursor, encode_cursor
from domain.metrics import EMPTY_SUMMARY, MetricsSummary
from domain.search_text import build_campaign_search_text, build_post_search_text, content_hash
from domain.timefmt import format_utc, parse_aware_datetime
from domain.tracking import build_tracking_url, is_valid_landing_url
from domain.x_text import contains_url, is_within_x_limit, weighted_length


def test_文字数_URLは23として数える() -> None:
    assert weighted_length("https://example.com/very/long/path?with=query") == 23
    assert weighted_length("a https://example.com b") == 1 + 1 + 23 + 1 + 1


def test_文字数_ラテン文字は1で日本語は2として数える() -> None:
    assert weighted_length("abc") == 3
    assert weighted_length("あいう") == 6


def test_文字数上限_280ちょうどは許可し281は拒否する() -> None:
    assert is_within_x_limit("a" * 280)
    assert not is_within_x_limit("a" * 281)
    assert is_within_x_limit("あ" * 140)
    assert not is_within_x_limit("あ" * 141)


def test_URL検出_httpとhttpsを検出する() -> None:
    assert contains_url("詳細は http://a.example.com")
    assert contains_url("HTTPS://A.EXAMPLE.COM")
    assert not contains_url("example.com はURLとして数えない")


def test_UTM付与_既存のutmは置き換えて他のクエリは残す() -> None:
    tracking = build_tracking_url(
        "https://example.com/lp?ref=a&utm_source=old#top",
        12,
        "0b7f1d3c-0000-4000-8000-000000000000",
    )

    assert tracking.utm_source == "x"
    assert tracking.utm_medium == "social"
    assert tracking.utm_campaign == "12"
    assert tracking.utm_content == "0b7f1d3c-0000-4000-8000-000000000000"
    assert "utm_source=old" not in tracking.tracked_url
    assert "ref=a" in tracking.tracked_url
    assert tracking.tracked_url.endswith("#top")
    assert tracking.landing_url == "https://example.com/lp?ref=a&utm_source=old#top"


@pytest.mark.parametrize(
    ("url", "valid"),
    [
        ("https://example.com", True),
        ("http://example.com/a?b=c", True),
        ("javascript:alert(1)", False),
        ("ftp://example.com", False),
        ("https://", False),
        ("https://exa mple.com", False),
        ("https://example.com:bad/path", False),
        ("https://example.com:99999/path", False),
        ("", False),
    ],
)
def test_遷移先URL検証_スキームとホストと空白を確認する(url: str, valid: bool) -> None:
    assert is_valid_landing_url(url) is valid


def test_日時表記_マイクロ秒は0でないときだけ付けUTCのZで終わる() -> None:
    assert format_utc(datetime(2026, 9, 21, 10, 0, tzinfo=UTC)) == "2026-09-21T10:00:00Z"
    assert (
        format_utc(datetime(2026, 9, 21, 10, 0, 0, 123456, tzinfo=UTC))
        == "2026-09-21T10:00:00.123456Z"
    )
    jst = timezone(timedelta(hours=9))
    assert format_utc(datetime(2026, 9, 21, 19, 0, tzinfo=jst)) == "2026-09-21T10:00:00Z"


def test_日時解析_タイムゾーンなしは拒否し空白に化けた加算記号を補う() -> None:
    with pytest.raises(ValueError, match="タイムゾーン"):
        parse_aware_datetime("2026-09-21T10:00:00")
    assert parse_aware_datetime("2026-09-21T19:00:00 09:00") == datetime(
        2026, 9, 21, 10, 0, tzinfo=UTC
    )
    assert parse_aware_datetime("2026-09-21T10:00:00Z") == datetime(2026, 9, 21, 10, 0, tzinfo=UTC)


def test_カーソル_符号化して復号すると元の値に戻る() -> None:
    token = encode_cursor("posts", {"id": 5, "published_at": "2026-09-21T10:00:00Z"})

    assert decode_cursor(token, "posts") == {"id": 5, "published_at": "2026-09-21T10:00:00Z"}


def test_カーソル_種別が違うときと壊れているときはCursorError() -> None:
    token = encode_cursor("posts", {"id": 1})

    with pytest.raises(CursorError):
        decode_cursor(token, "campaigns")
    with pytest.raises(CursorError):
        decode_cursor("!!broken!!", "posts")


def test_流入率_PVが0のときNoneでそれ以外は割り算のまま丸めない() -> None:
    assert EMPTY_SUMMARY.landing_rate is None
    assert MetricsSummary(1, 1, 0, 0, 3, 1).landing_rate == 1 / 3


def test_検索テキスト_施策はタイトルを含めず空白を正規化する() -> None:
    text = build_campaign_search_text("20代  会社員", "背景", "目的", "計画")

    assert text == "ターゲット像: 20代 会社員\n実施背景: 背景\n施策目的: 目的\n施策内容: 計画"


def test_検索テキスト_投稿はURLを除去する() -> None:
    assert (
        build_post_search_text("春です https://example.com/lp 資料はこちら")
        == "春です 資料はこちら"
    )


def test_内容ハッシュ_同じ内容は同じで異なる内容は異なる() -> None:
    assert content_hash("a") == content_hash("a")
    assert content_hash("a") != content_hash("b")


def test_施策の業務条件_タイトルの改行と制御文字を拒否し本文の改行は許可する() -> None:
    ok = CampaignContent("題", "対象\n改行可", "背景", "目的", "計画")

    assert campaign_field_errors(ok) == []
    assert campaign_field_errors(CampaignContent("a\nb", "x", "x", "x", "x"))[0]["field"] == "title"
    assert (
        campaign_field_errors(CampaignContent("題", "x\x00", "x", "x", "x"))[0]["field"]
        == "target_profile"
    )
