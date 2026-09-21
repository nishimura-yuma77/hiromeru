"""UTM付きURLの生成（API_DESIGN 3.1）。LLMを使わず決定論的に生成する。"""

from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from domain.constants import MAX_LANDING_URL_LENGTH

UTM_SOURCE = "x"
UTM_MEDIUM = "social"
_UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_content")


@dataclass(frozen=True)
class TrackingUrl:
    """UTMパラメータとトラッキングURL。"""

    landing_url: str
    utm_source: str
    utm_medium: str
    utm_campaign: str
    utm_content: str
    tracked_url: str


def is_valid_landing_url(url: str) -> bool:
    """http/https で、ホストを持つ、長さ上限内のURLか。"""
    if not url or len(url) > MAX_LANDING_URL_LENGTH or any(char.isspace() for char in url):
        return False
    parts = urlsplit(url)
    return parts.scheme in ("http", "https") and bool(parts.hostname)


def build_tracking_url(landing_url: str, campaign_id: int, idempotency_key: str) -> TrackingUrl:
    """遷移先URLへUTMパラメータを付与する。

    `utm_campaign` は施策ID、`utm_content` は Idempotency-Key から生成する。
    遷移先URLに同名のUTMパラメータがある場合は、アプリケーションの値で置き換える。
    """
    parts = urlsplit(landing_url)
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in _UTM_KEYS]
    utm = [
        ("utm_source", UTM_SOURCE),
        ("utm_medium", UTM_MEDIUM),
        ("utm_campaign", str(campaign_id)),
        ("utm_content", idempotency_key),
    ]
    tracked = urlunsplit(parts._replace(query=urlencode(kept + utm)))
    return TrackingUrl(
        landing_url=landing_url,
        utm_source=UTM_SOURCE,
        utm_medium=UTM_MEDIUM,
        utm_campaign=str(campaign_id),
        utm_content=idempotency_key,
        tracked_url=tracked,
    )
