import html
import logging

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from src.connections.exceptions import (
    ConnectOAuthFailed,
    ConnectOAuthInvalidTicket,
    ConnectOAuthNotConfigured,
)
from src.connections.github_oauth import (
    authorization_url as github_authorization_url,
)
from src.connections.github_oauth import (
    exchange_code as github_exchange_code,
)
from src.connections.github_oauth import oauth_is_configured as github_oauth_is_configured
from src.connections.granola_oauth import (
    exchange_code as granola_exchange_code,
)
from src.connections.granola_oauth import (
    start_authorization_url as granola_start_authorization_url,
)
from src.connections.pages import oauth_page
from src.connections.repository import save_secret
from src.notify import notify_owner

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


@router.get(
    "/github",
    response_model=None,
    summary="Start GitHub OAuth",
    description="Requires a short-lived ticket from Discord (connect github). Redirects to GitHub consent.",
    responses={
        302: {"description": "Redirect to GitHub"},
        401: {"description": "Missing or expired ticket"},
        503: {"description": "GITHUB_CLIENT_ID / SECRET not set"},
    },
)
async def start_github_oauth(ticket: str = Query(default="")) -> RedirectResponse | HTMLResponse:
    if not github_oauth_is_configured():
        return oauth_page(
            "GitHub is not configured",
            "Set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET, then say “connect github” in Discord.",
            503,
        )
    try:
        url = github_authorization_url(ticket.strip())
    except ConnectOAuthInvalidTicket:
        return oauth_page(
            "Link expired",
            "This connect link is invalid or expired. Say “connect github” in Discord for a new one.",
            401,
        )
    except ConnectOAuthNotConfigured:
        return oauth_page(
            "GitHub is not configured",
            "Set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET, then say “connect github” in Discord.",
            503,
        )
    return RedirectResponse(url, status_code=302)


@router.get(
    "/github/callback",
    response_model=None,
    summary="GitHub OAuth callback",
    description="Exchanges the authorization code and stores the user token in Postgres.",
    responses={
        400: {"description": "Access denied or missing code"},
        401: {"description": "Invalid state ticket"},
    },
)
async def github_oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> HTMLResponse:
    if error:
        return oauth_page(
            "GitHub connect cancelled",
            "You denied access. Say “connect github” in Discord to try again.",
            400,
        )
    if not code or not state:
        return oauth_page("GitHub connect failed", "Missing code or state from GitHub.", 400)
    try:
        bundle = await github_exchange_code(code, state)
    except ConnectOAuthInvalidTicket:
        return oauth_page(
            "Link expired",
            "This connect link is invalid or expired. Say “connect github” in Discord for a new one.",
            401,
        )
    except Exception:
        logger.exception("GitHub token exchange failed")
        return oauth_page(
            "GitHub connect failed",
            "Could not exchange the authorization code. Say “connect github” in Discord and try again.",
            400,
        )
    await save_secret(
        provider="github",
        token=bundle.access_token,
        extra={
            "kind": "oauth",
            "username": bundle.username,
            "scopes": bundle.scopes,
        },
    )
    who = bundle.username or "your GitHub account"
    try:
        await notify_owner(
            f"**GitHub connected** as {bundle.username or 'your account'}. "
            "Repos, PRs, and CI tools are ready."
        )
    except Exception:
        logger.exception("failed to notify owner after GitHub connect")
    return oauth_page(
        "GitHub connected",
        f"Connected as <strong>{html.escape(who)}</strong>. "
        "You can close this tab and go back to Discord.",
    )


@router.get(
    "/granola",
    response_model=None,
    summary="Start Granola MCP OAuth",
    description="Registers a public OAuth client (DCR) and redirects to Granola sign-in.",
    responses={
        302: {"description": "Redirect to Granola"},
        401: {"description": "Missing or expired ticket"},
        400: {"description": "Dynamic client registration failed"},
    },
)
async def start_granola_oauth(ticket: str = Query(default="")) -> RedirectResponse | HTMLResponse:
    try:
        url = await granola_start_authorization_url(ticket.strip())
    except ConnectOAuthInvalidTicket:
        return oauth_page(
            "Link expired",
            "This connect link is invalid or expired. Say “connect granola” in Discord for a new one.",
            401,
        )
    except ConnectOAuthFailed:
        return oauth_page(
            "Granola connect failed",
            "Could not register with Granola. Say “connect granola” in Discord and try again.",
            400,
        )
    return RedirectResponse(url, status_code=302)


@router.get(
    "/granola/callback",
    response_model=None,
    summary="Granola OAuth callback",
    description="Exchanges the authorization code and stores MCP tokens in Postgres.",
    responses={
        400: {"description": "Access denied or missing code"},
        401: {"description": "Invalid state ticket"},
    },
)
async def granola_oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> HTMLResponse:
    if error:
        return oauth_page(
            "Granola connect cancelled",
            "You denied access. Say “connect granola” in Discord to try again.",
            400,
        )
    if not code or not state:
        return oauth_page("Granola connect failed", "Missing code or state from Granola.", 400)
    try:
        bundle = await granola_exchange_code(code, state)
    except ConnectOAuthInvalidTicket:
        return oauth_page(
            "Link expired",
            "This connect link is invalid or expired. Say “connect granola” in Discord for a new one.",
            401,
        )
    except Exception:
        logger.exception("Granola token exchange failed")
        return oauth_page(
            "Granola connect failed",
            "Could not exchange the authorization code. Say “connect granola” in Discord and try again.",
            400,
        )
    extra = {
        "kind": "mcp_oauth",
        "client_id": bundle.client_id,
        "refresh_token": bundle.refresh_token,
        "token_expiry": bundle.token_expiry.isoformat() if bundle.token_expiry else None,
        "email": bundle.email,
        "scopes": bundle.scopes,
        "mcp_url": "https://mcp.granola.ai/mcp",
    }
    await save_secret(provider="granola", token=bundle.access_token, extra=extra)
    who = html.escape(bundle.email or "your Granola account")
    try:
        await notify_owner(
            f"**Granola connected** as {bundle.email or 'your account'}. Meeting tools are ready."
        )
    except Exception:
        logger.exception("failed to notify owner after Granola connect")
    return oauth_page(
        "Granola connected",
        f"Connected as <strong>{who}</strong>. You can close this tab and go back to Discord.",
    )
