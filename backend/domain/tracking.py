"""UTM付きURLの生成（API_DESIGN 3.1）。LLMを使わず決定論的に生成する。"""

import ipaddress
import unicodedata
from dataclasses import dataclass
from urllib.parse import unquote_plus, urlencode, urlsplit, urlunsplit

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


def _is_valid_hostname(hostname: str) -> bool:
    """URL Parserが許容する曖昧なHost表現を除外する。"""
    if not hostname or any(
        ord(char) < 33 or char in "\\%" or unicodedata.category(char) == "Cf" for char in hostname
    ):
        return False
    if ":" in hostname:
        try:
            return isinstance(ipaddress.ip_address(hostname), ipaddress.IPv6Address)
        except ValueError:
            return False
    candidate = hostname.removesuffix(".")
    try:
        ascii_hostname = candidate.encode("idna").decode("ascii")
    except UnicodeError:
        return False
    if not ascii_hostname or len(ascii_hostname) > 253:
        return False
    if all(char.isdigit() or char == "." for char in ascii_hostname):
        try:
            return isinstance(ipaddress.ip_address(ascii_hostname), ipaddress.IPv4Address)
        except ValueError:
            return False
    labels = ascii_hostname.split(".")
    if all(
        label.isdigit()
        or (
            label.lower().startswith("0x")
            and bool(label[2:])
            and all(char in "0123456789abcdefABCDEF" for char in label[2:])
        )
        for label in labels
    ):
        return False
    return all(
        0 < len(label) <= 63
        and not label.startswith("-")
        and not label.endswith("-")
        and all(char.isascii() and (char.isalnum() or char == "-") for char in label)
        for label in labels
    )


def is_valid_landing_url(url: str) -> bool:
    """http/https で、ホストを持つ、長さ上限内のURLか。"""
    if not url or len(url) > MAX_LANDING_URL_LENGTH or any(char.isspace() for char in url):
        return False
    try:
        parts = urlsplit(url)
        _ = parts.port  # Port表記と範囲を検証する。
        hostname = parts.hostname or ""
        return (
            parts.scheme.lower() in ("http", "https")
            and _is_valid_hostname(hostname)
            and parts.username is None
            and parts.password is None
        )
    except ValueError:
        return False


def build_tracking_url(landing_url: str, campaign_id: int, idempotency_key: str) -> TrackingUrl:
    """遷移先URLへUTMパラメータを付与する。

    `utm_campaign` は施策ID、`utm_content` は Idempotency-Key から生成する。
    遷移先URLに同名のUTMパラメータがある場合は、アプリケーションの値で置き換える。
    """
    parts = urlsplit(landing_url)
    segments = parts.query.split("&") if parts.query else []
    kept = [
        segment for segment in segments if unquote_plus(segment.partition("=")[0]) not in _UTM_KEYS
    ]
    utm = [
        ("utm_source", UTM_SOURCE),
        ("utm_medium", UTM_MEDIUM),
        ("utm_campaign", str(campaign_id)),
        ("utm_content", idempotency_key),
    ]
    existing_query = "&".join(kept) if any(kept) else ""
    encoded_utm = urlencode(utm)
    query = f"{existing_query}&{encoded_utm}" if existing_query else encoded_utm
    tracked = urlunsplit(parts._replace(query=query, fragment=""))
    if "#" in landing_url:
        tracked = f"{tracked}#{parts.fragment}"
    return TrackingUrl(
        landing_url=landing_url,
        utm_source=UTM_SOURCE,
        utm_medium=UTM_MEDIUM,
        utm_campaign=str(campaign_id),
        utm_content=idempotency_key,
        tracked_url=tracked,
    )
