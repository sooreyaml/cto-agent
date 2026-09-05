import hashlib
import hmac
import time

import pytest
from httpx import ASGITransport, AsyncClient
from src.main import app
from src.slack.client import verify_slack_signature


def _sign(body: str, timestamp: str, secret: str = "test-signing-secret") -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        f"v0:{timestamp}:{body}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"v0={digest}"


def test_verify_missing_headers() -> None:
    valid, reason = verify_slack_signature("{}", None, None)
    assert valid is False
    assert reason == "missing_headers"


def test_verify_expired_timestamp() -> None:
    ts = str(int(time.time()) - 400)
    valid, reason = verify_slack_signature("{}", ts, _sign("{}", ts))
    assert valid is False
    assert reason == "timestamp_expired"


def test_verify_ok() -> None:
    ts = str(int(time.time()))
    body = '{"type":"url_verification","challenge":"abc"}'
    valid, reason = verify_slack_signature(body, ts, _sign(body, ts))
    assert valid is True
    assert reason == "ok"


@pytest.mark.asyncio
async def test_slack_events_rejects_bad_signature() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/slack/events", content=b"{}", headers={"content-type": "application/json"}
        )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_slack_url_verification() -> None:
    ts = str(int(time.time()))
    body = '{"type":"url_verification","challenge":"abc"}'
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/slack/events",
            content=body.encode(),
            headers={
                "content-type": "application/json",
                "x-slack-request-timestamp": ts,
                "x-slack-signature": _sign(body, ts),
            },
        )
    assert res.status_code == 200
    assert res.json() == {"challenge": "abc"}
