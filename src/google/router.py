import html
import logging

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from src.google.exceptions import GoogleOAuthInvalidTicket, GoogleOAuthNotConfigured
from src.google.service import (
    authorization_url,
    exchange_code,
    load_account,
    oauth_is_configured,
    upsert_google_account,
)
from src.integrations.google import invalidate_google_credentials
from src.slack.client import post_dm_to_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["google"])


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>{html.escape(title)}</title></head>
<body style="font-family: system-ui, sans-serif; max-width: 36rem; margin: 3rem auto; line-height: 1.5;">
  <h1>{html.escape(title)}</h1>
  <p>{body}</p>
</body>
</html>
""",
        status_code=status,
    )


@router.get(
    "/google",
    response_model=None,
    summary="Start Google OAuth",
    description="Requires a short-lived ticket from Slack (Connect Google). Redirects to Google consent.",
    responses={
        302: {"description": "Redirect to Google"},
        401: {"description": "Missing or expired ticket"},
        503: {"description": "GOOGLE_CLIENT_ID / SECRET not set"},
    },
)
async def start_google_oauth(
    ticket: str = Query(default=""),
) -> RedirectResponse | HTMLResponse:
    if not oauth_is_configured():
        return _page(
            "Google is not configured",
            "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET, then say “connect google” in Slack.",
            503,
        )
    try:
        url = authorization_url(ticket.strip())
    except GoogleOAuthInvalidTicket:
        return _page(
            "Link expired",
            "This connect link is invalid or expired. Say “connect google” in Slack for a new one.",
            401,
        )
    except GoogleOAuthNotConfigured:
        return _page(
            "Google is not configured",
            "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET, then say “connect google” in Slack.",
            503,
        )
    return RedirectResponse(url, status_code=302)


@router.get(
    "/google/callback",
    response_model=None,
    summary="Google OAuth callback",
    description="Exchanges the authorization code and stores refresh tokens in Postgres.",
    responses={
        400: {"description": "Access denied or missing code"},
        401: {"description": "Invalid state ticket"},
    },
)
async def google_oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> HTMLResponse:
    if error:
        return _page(
            "Google connect cancelled",
            "You denied access. Say “connect google” in Slack to try again.",
            400,
        )
    if not code or not state:
        return _page("Google connect failed", "Missing code or state from Google.", 400)
    try:
        bundle = exchange_code(code, state)
    except GoogleOAuthInvalidTicket:
        return _page(
            "Link expired",
            "This connect link is invalid or expired. Say “connect google” in Slack for a new one.",
            401,
        )
    except Exception:
        logger.exception("Google token exchange failed")
        return _page(
            "Google connect failed",
            "Could not exchange the authorization code. Say “connect google” in Slack and try again.",
            400,
        )
    if not bundle.refresh_token:
        existing = await load_account(bundle.slack_user_id)
        if existing is None:
            return _page(
                "Google connect failed",
                "Google did not return a refresh token. Remove this app at "
                "https://myaccount.google.com/permissions then connect again.",
                400,
            )
        saved = await upsert_google_account(
            slack_user_id=bundle.slack_user_id,
            refresh_token=existing.refresh_token,
            access_token=bundle.access_token or existing.access_token,
            token_expiry=bundle.token_expiry or existing.token_expiry,
            scopes=bundle.scopes or existing.scopes,
            email=bundle.email or existing.email,
        )
    else:
        saved = await upsert_google_account(
            slack_user_id=bundle.slack_user_id,
            refresh_token=bundle.refresh_token,
            access_token=bundle.access_token,
            token_expiry=bundle.token_expiry,
            scopes=bundle.scopes,
            email=bundle.email,
        )
    invalidate_google_credentials()
    email_html = html.escape(saved.email or "your Google account")
    try:
        await post_dm_to_user(
            saved.slack_user_id,
            f"*Google connected* as {saved.email or 'your account'}. Gmail and Calendar are ready.",
            mrkdwn=True,
        )
    except Exception:
        logger.exception("failed to DM Slack after Google connect")
    return _page(
        "Google connected",
        f"Connected as <strong>{email_html}</strong>. You can close this tab and go back to Slack.",
    )
