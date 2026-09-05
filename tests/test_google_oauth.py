import pytest
from httpx import ASGITransport, AsyncClient
from src.config import get_settings
from src.google.constants import TICKET_TTL_SECONDS
from src.google.exceptions import GoogleOAuthInvalidTicket
from src.google.service import (
    is_google_connect_command,
    issue_connect_ticket,
    parse_connect_ticket,
)
from src.main import app


@pytest.fixture
def google_oauth_env() -> None:
    settings = get_settings()
    previous = (settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET)
    settings.GOOGLE_CLIENT_ID = "cid.apps.googleusercontent.com"
    settings.GOOGLE_CLIENT_SECRET = "gsecret"
    yield
    settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET = previous


def test_connect_command_matches() -> None:
    assert is_google_connect_command("connect google")
    assert is_google_connect_command("Please reconnect Google!")
    assert is_google_connect_command("link gmail")
    assert not is_google_connect_command("what's on my calendar")


def test_ticket_roundtrip(google_oauth_env: None) -> None:
    ticket = issue_connect_ticket()
    assert parse_connect_ticket(ticket) == get_settings().SLACK_USER_ID


def test_ticket_rejects_tamper(google_oauth_env: None) -> None:
    ticket = issue_connect_ticket()
    with pytest.raises(GoogleOAuthInvalidTicket):
        parse_connect_ticket(ticket[:-2] + "ab")


def test_ticket_rejects_wrong_user(google_oauth_env: None) -> None:
    ticket = issue_connect_ticket(slack_user_id="UOTHER")
    with pytest.raises(GoogleOAuthInvalidTicket):
        parse_connect_ticket(ticket)


def test_ticket_expired(google_oauth_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.google.service.time.time", lambda: 1_700_000_000)
    ticket = issue_connect_ticket()
    monkeypatch.setattr(
        "src.google.service.time.time",
        lambda: 1_700_000_000 + TICKET_TTL_SECONDS + 5,
    )
    with pytest.raises(GoogleOAuthInvalidTicket):
        parse_connect_ticket(ticket)


@pytest.mark.asyncio
async def test_start_oauth_not_configured() -> None:
    settings = get_settings()
    previous = (settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET)
    settings.GOOGLE_CLIENT_ID = ""
    settings.GOOGLE_CLIENT_SECRET = ""
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            res = await client.get("/auth/google", params={"ticket": "x"})
        assert res.status_code == 503
        assert "not configured" in res.text.lower()
    finally:
        settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET = previous


@pytest.mark.asyncio
async def test_start_oauth_expired_ticket(google_oauth_env: None) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/auth/google")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_start_oauth_redirects(google_oauth_env: None) -> None:
    ticket = issue_connect_ticket()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/auth/google", params={"ticket": ticket}, follow_redirects=False)
    assert res.status_code == 302
    location = res.headers["location"]
    assert "accounts.google.com" in location
    assert "access_type=offline" in location
    assert "prompt=consent" in location


@pytest.mark.asyncio
async def test_callback_denied() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/auth/google/callback", params={"error": "access_denied"})
    assert res.status_code == 400
    assert "denied" in res.text.lower() or "cancelled" in res.text.lower()
