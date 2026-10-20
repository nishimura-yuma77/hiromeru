"""招待メールの送信クライアント（AWS SES v2）。BE_STD 8.3、API_DESIGN 11.2。

SESの成功応答（MessageId）は送信受付を示し、配達完了は示さない。副作用のある呼び出しのため、
クライアント自体は再試行しない。送信操作内の自動再試行は、明確なスロットリング応答だけを
サービス側で行う。
"""

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from clients.errors import UpstreamError
from core.clock import Clock

_SERVICE = "ses"
# 明確なスロットリング応答。これ以外の4xx（408を除く）は送信失敗が確定したものとする。
_THROTTLING_ERROR_TYPES = frozenset({"TooManyRequestsException", "ThrottlingException"})


@dataclass(frozen=True)
class EmailMessage:
    """送信するテキストメール。本文にはトークン付きの招待リンクを含む。"""

    to: str
    subject: str
    body: str


class EmailThrottledError(UpstreamError):
    """SESが明確なスロットリング応答を返した。同じリンクで再試行してよい。"""


class EmailRejectedError(UpstreamError):
    """SESが送信の失敗を確定して返した。送られていないことが確実。"""

    def __init__(self, status_code: int, error_type: str) -> None:
        """失敗のHTTP StatusとSESのエラー種別を保持する。本文は保持しない。"""
        super().__init__(f"SESが送信を拒否しました (status={status_code}, type={error_type})")
        self.status_code = status_code
        self.error_type = error_type


class EmailOutcomeUnknownError(UpstreamError):
    """SESの受付結果を確定できなかった（5xx・408・Timeout・通信エラー・不正な応答）。

    受付済みの可能性を否定できないため、自動で再送しない。
    """


class EmailClient(Protocol):
    """招待メールの送信。成功時はSESのMessageIdを返す。"""

    async def send(self, message: EmailMessage) -> str:
        """メールを1回だけ送信する。"""
        ...


def _hmac(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode(), hashlib.sha256).digest()


def sigv4_headers(
    *,
    method: str,
    url: str,
    body: bytes,
    region: str,
    service: str,
    access_key_id: str,
    secret_access_key: str,
    session_token: str | None,
    now: datetime,
) -> dict[str, str]:
    """AWS Signature Version 4 の認証Headerを返す。Queryを持たないURLだけを扱う。"""
    parts = urlsplit(url)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(body).hexdigest()
    headers = {"host": parts.netloc, "x-amz-date": amz_date}
    if session_token:
        headers["x-amz-security-token"] = session_token
    signed_headers = ";".join(sorted(headers))
    canonical_headers = "".join(f"{name}:{headers[name]}\n" for name in sorted(headers))
    canonical_request = "\n".join(
        [method, parts.path or "/", parts.query, canonical_headers, signed_headers, payload_hash]
    )
    scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            scope,
            hashlib.sha256(canonical_request.encode()).hexdigest(),
        ]
    )
    key = _hmac(f"AWS4{secret_access_key}".encode(), date_stamp)
    for part in (region, service, "aws4_request"):
        key = _hmac(key, part)
    signature = hmac.new(key, string_to_sign.encode(), hashlib.sha256).hexdigest()
    authorization = (
        f"AWS4-HMAC-SHA256 Credential={access_key_id}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    result = {"Authorization": authorization, "X-Amz-Date": amz_date}
    if session_token:
        result["X-Amz-Security-Token"] = session_token
    return result


def _error_type(response: httpx.Response) -> str:
    raw = response.headers.get("x-amzn-errortype", "")
    if not raw:
        try:
            payload = response.json()
        except ValueError:
            return ""
        raw = str(payload.get("__type", "")) if isinstance(payload, dict) else ""
    # `TooManyRequestsException:http://internal.amazon.com/...` の形式で返ることがある。
    return raw.split(":", 1)[0].rsplit("#", 1)[-1]


class SesEmailClient:
    """SES v2 の SendEmail を1回だけ呼ぶクライアント。SDKを使わず、自動再試行もしない。"""

    def __init__(
        self,
        *,
        region: str,
        from_address: str,
        access_key_id: str,
        secret_access_key: str,
        session_token: str | None,
        timeout_seconds: float,
        clock: Clock,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """クライアントを作る。`transport` はテストで差し替える。"""
        self._url = f"https://email.{region}.amazonaws.com/v2/email/outbound-emails"
        self._region = region
        self._from = from_address
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._session_token = session_token or None
        self._timeout = timeout_seconds
        self._clock = clock
        self._transport = transport

    async def send(self, message: EmailMessage) -> str:
        """メールを送信し、SESのMessageIdを返す。"""
        body = json.dumps(
            {
                "FromEmailAddress": self._from,
                "Destination": {"ToAddresses": [message.to]},
                "Content": {
                    "Simple": {
                        "Subject": {"Data": message.subject, "Charset": "UTF-8"},
                        "Body": {"Text": {"Data": message.body, "Charset": "UTF-8"}},
                    }
                },
            },
            ensure_ascii=False,
        ).encode()
        headers = sigv4_headers(
            method="POST",
            url=self._url,
            body=body,
            region=self._region,
            service=_SERVICE,
            access_key_id=self._access_key_id,
            secret_access_key=self._secret_access_key,
            session_token=self._session_token,
            now=self._clock.now(),
        )
        headers["Content-Type"] = "application/json"
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=self._timeout
            ) as client:
                response = await client.post(self._url, headers=headers, content=body)
        except (httpx.TimeoutException, httpx.TransportError):
            raise EmailOutcomeUnknownError("SESの受付結果を確定できませんでした") from None
        return self._message_id(response)

    @staticmethod
    def _message_id(response: httpx.Response) -> str:
        status = response.status_code
        if status == httpx.codes.OK:
            try:
                message_id = response.json()["MessageId"]
            except (ValueError, KeyError, TypeError):
                raise EmailOutcomeUnknownError("SESの応答を解釈できませんでした") from None
            if not isinstance(message_id, str) or not message_id:
                raise EmailOutcomeUnknownError("SESの応答にMessageIdがありません")
            return message_id
        error_type = _error_type(response)
        if status == httpx.codes.TOO_MANY_REQUESTS or error_type in _THROTTLING_ERROR_TYPES:
            raise EmailThrottledError("SESがスロットリング応答を返しました")
        if 400 <= status < 500 and status != httpx.codes.REQUEST_TIMEOUT:
            raise EmailRejectedError(status, error_type or "Unknown")
        raise EmailOutcomeUnknownError(f"SESが想定外の応答を返しました ({status})")


class FakeEmailClient:
    """外部へ送信せず、送信内容を記録して固定PrefixのMessageIdを返す。"""

    def __init__(self) -> None:
        """送信済みのメールを空にする。"""
        self.sent: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> str:
        """送信内容を記録する。"""
        self.sent.append(message)
        return f"fake-ses-{len(self.sent)}"
