import pytest
from httpx import ASGITransport, AsyncClient
from src.config import get_settings
from src.connections.catalog import get_provider
from src.connections.commands import match_connect_command
from src.connections.constants import TICKET_TTL_SECONDS
from src.connections.exceptions import ConnectOAuthInvalidTicket
from src.connections.github_oauth import authorization_url as github_authorization_url
from src.connections.granola_oauth import authorization_url as granola_authorization_url
from src.connections.granola_oauth import register_payload
from src.connections.repository import public_extra
from src.connections.ticket import issue_ticket, parse_ticket
from src.main import app


@pytest.fixture
def github_oauth_env() -> None:
    settings = get_settings()
    previous = (settings.GITHUB_CLIENT_ID, settings.GITHUB_CLIENT_SECRET)
    settings.GITHUB_CLIENT_ID = "github-client"
    settings.GITHUB_CLIENT_SECRET = "github-secret"
    yield
    settings.GITHUB_CLIENT_ID, settings.GITHUB_CLIENT_SECRET = previous


def test_connect_commands() -> None:
    assert match_connect_command("connect github") == "github"
    assert match_connect_command("Please reconnect Granola!") == "granola"
    assert match_connect_command("connect google") == "google"
    assert match_connect_command("what's on my calendar") is None


def test_ticket_roundtrip() -> None:
    ticket = issue_ticket(client_id="cid-1")
    parsed = parse_ticket(ticket)
    assert parsed.slack_user_id == get_settings().DISCORD_USER_ID
    assert parsed.client_id == "cid-1"
    assert len(parsed.code_verifier) >= 43


def test_ticket_rejects_tamper() -> None:
    ticket = issue_ticket()
    with pytest.raises(ConnectOAuthInvalidTicket):
        parse_ticket(ticket[:-2] + "ab")


def test_ticket_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.connections.ticket.time.time", lambda: 1_700_000_000)
    ticket = issue_ticket()
    monkeypatch.setattr(
        "src.connections.ticket.time.time",
        lambda: 1_700_000_000 + TICKET_TTL_SECONDS + 5,
    )
    with pytest.raises(ConnectOAuthInvalidTicket):
        parse_ticket(ticket)


def test_github_authorization_url(github_oauth_env: None) -> None:
    ticket = issue_ticket()
    url = github_authorization_url(ticket)
    assert "github.com/login/oauth/authorize" in url
    assert "client_id=github-client" in url
    assert "scope=repo" in url


def test_granola_authorization_url() -> None:
    ticket = issue_ticket(client_id="granola-app")
    url = granola_authorization_url(ticket)
    assert "mcp-auth.granola.ai/oauth2/authorize" in url
    assert "code_challenge" in url
    assert "resource=" in url
    payload = register_payload()
    assert payload["token_endpoint_auth_method"] == "none"
    assert payload["redirect_uris"][0].endswith("/auth/granola/callback")


def test_catalog_oauth_providers() -> None:
    assert get_provider("github")["auth"] == "oauth"
    assert get_provider("granola")["auth"] == "oauth"


def test_public_extra_hides_tokens() -> None:
    shown = public_extra(
        {
            "kind": "mcp_oauth",
            "email": "me@example.com",
            "refresh_token": "secret-refresh",
            "client_id": "cid",
            "username": "octocat",
        }
    )
    assert shown == {"kind": "mcp_oauth", "email": "me@example.com", "username": "octocat"}


@pytest.mark.asyncio
async def test_start_github_not_configured() -> None:
    settings = get_settings()
    previous = (settings.GITHUB_CLIENT_ID, settings.GITHUB_CLIENT_SECRET)
    settings.GITHUB_CLIENT_ID = ""
    settings.GITHUB_CLIENT_SECRET = ""
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            res = await client.get("/auth/github", params={"ticket": "x"})
        assert res.status_code == 503
        assert "not configured" in res.text.lower()
    finally:
        settings.GITHUB_CLIENT_ID, settings.GITHUB_CLIENT_SECRET = previous


@pytest.mark.asyncio
async def test_start_github_redirects(github_oauth_env: None) -> None:
    ticket = issue_ticket()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/auth/github", params={"ticket": ticket}, follow_redirects=False)
    assert res.status_code == 302
    assert "github.com/login/oauth/authorize" in res.headers["location"]


@pytest.mark.asyncio
async def test_start_granola_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_client() -> str:
        return "granola-dcr-id"

    monkeypatch.setattr("src.connections.granola_oauth.resolve_client_id", fake_client)
    ticket = issue_ticket()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/auth/granola", params={"ticket": ticket}, follow_redirects=False)
    assert res.status_code == 302
    location = res.headers["location"]
    assert "mcp-auth.granola.ai" in location
    assert "granola-dcr-id" in location


@pytest.mark.asyncio
async def test_github_callback_denied() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/auth/github/callback", params={"error": "access_denied"})
    assert res.status_code == 400
    assert "denied" in res.text.lower() or "cancelled" in res.text.lower()
