"""SES v2 クライアントの署名と応答分類（BE_STD 8.3）。外部へは送信しない。"""

import json
from datetime import UTC, datetime

import httpx
import pytest

from clients.email import (
    EmailMessage,
    EmailOutcomeUnknownError,
    EmailRejectedError,
    EmailThrottledError,
    SesEmailClient,
    sigv4_headers,
)
from tests.support.fakes import FixedClock

MESSAGE = EmailMessage(to="to@example.com", subject="件名", body="本文 https://x/?token=abc")


def test_SigV4_AWS公開テストスイートのget_vanillaと同じ署名になる() -> None:
    headers = sigv4_headers(
        method="GET",
        url="https://example.amazonaws.com/",
        body=b"",
        region="us-east-1",
        service="service",
        access_key_id="AKIDEXAMPLE",
        secret_access_key="wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY",
        session_token=None,
        now=datetime(2015, 8, 30, 12, 36, tzinfo=UTC),
    )

    assert headers["X-Amz-Date"] == "20150830T123600Z"
    assert headers["Authorization"] == (
        "AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20150830/us-east-1/service/aws4_request, "
        "SignedHeaders=host;x-amz-date, "
        "Signature=5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31"
    )


def test_SigV4_一時Credentialのセッショントークンを署名対象に含める() -> None:
    headers = sigv4_headers(
        method="POST",
        url="https://email.ap-northeast-1.amazonaws.com/v2/email/outbound-emails",
        body=b"{}",
        region="ap-northeast-1",
        service="ses",
        access_key_id="AKID",
        secret_access_key="secret",
        session_token="session-token",
        now=datetime(2026, 10, 21, tzinfo=UTC),
    )

    assert headers["X-Amz-Security-Token"] == "session-token"
    assert "SignedHeaders=host;x-amz-date;x-amz-security-token" in headers["Authorization"]


def _client(handler: httpx.MockTransport) -> SesEmailClient:
    return SesEmailClient(
        region="ap-northeast-1",
        from_address="noreply@example.com",
        access_key_id="AKID",
        secret_access_key="secret",
        session_token=None,
        timeout_seconds=5,
        clock=FixedClock(),
        transport=handler,
    )


async def test_SES_受付成功ならMessageIdを返しSendEmailのBodyを送る() -> None:
    captured: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"MessageId": "message-1"})

    message_id = await _client(httpx.MockTransport(handle)).send(MESSAGE)

    assert message_id == "message-1"
    [request] = captured
    assert str(request.url) == (
        "https://email.ap-northeast-1.amazonaws.com/v2/email/outbound-emails"
    )
    assert request.headers["authorization"].startswith("AWS4-HMAC-SHA256 ")
    body = json.loads(request.content)
    assert body["FromEmailAddress"] == "noreply@example.com"
    assert body["Destination"] == {"ToAddresses": ["to@example.com"]}
    assert body["Content"]["Simple"]["Body"]["Text"]["Data"] == MESSAGE.body


@pytest.mark.parametrize(
    ("status", "headers", "payload"),
    [
        (429, {"x-amzn-ErrorType": "TooManyRequestsException"}, {}),
        (400, {"x-amzn-ErrorType": "ThrottlingException:http://internal"}, {}),
        (400, {}, {"__type": "com.amazonaws#TooManyRequestsException"}),
    ],
)
async def test_SES_明確なスロットリング応答だけを再試行可能として返す(
    status: int, headers: dict[str, str], payload: dict[str, str]
) -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(status, headers=headers, json=payload))

    with pytest.raises(EmailThrottledError):
        await _client(transport).send(MESSAGE)


async def test_SES_408以外の4xxは送信失敗の確定として返す() -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(400, headers={"x-amzn-ErrorType": "MessageRejected"}, json={})
    )

    with pytest.raises(EmailRejectedError) as raised:
        await _client(transport).send(MESSAGE)

    assert (raised.value.status_code, raised.value.error_type) == (400, "MessageRejected")


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, json={}),
        httpx.Response(503, json={}),
        httpx.Response(408, json={}),
        httpx.Response(200, json={}),
        httpx.Response(200, text="not json"),
    ],
)
async def test_SES_5xx_408_不正な応答は結果不明として返す(response: httpx.Response) -> None:
    with pytest.raises(EmailOutcomeUnknownError):
        await _client(httpx.MockTransport(lambda _: response)).send(MESSAGE)


async def test_SES_TimeoutとTransportErrorは結果不明として返す() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("broken", request=request)

    for handler in (timeout, broken):
        with pytest.raises(EmailOutcomeUnknownError):
            await _client(httpx.MockTransport(handler)).send(MESSAGE)
