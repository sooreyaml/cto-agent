from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlencode

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.database import async_session_factory, run_from_thread
from src.exceptions import ConfigError
from src.google.constants import CONNECT_COMMANDS, SCOPES, TICKET_TTL_SECONDS
from src.google.exceptions import GoogleOAuthInvalidTicket, GoogleOAuthNotConfigured
from src.google.models import GoogleAccount

logger = logging.getLogger(__name__)

_env_refresh_rejected = False
_connect_prefixes = ("please ", "can you ", "could you ", "hey ", "ok ")


@dataclass(frozen=True)
class ConnectTicket:
    slack_user_id: str
    code_verifier: str


@dataclass(frozen=True)
class GoogleTokenBundle:
    slack_user_id: str
    email: str | None
    refresh_token: str
    access_token: str | None
    token_expiry: datetime | None
    scopes: str | None
    id: str | None = None
    label: str | None = None
    is_default: bool = False

    @property
    def key(self) -> str:
        if self.email:
            return self.email.lower()
        return self.id or self.slack_user_id


def oauth_is_configured() -> bool:
    settings = get_settings()
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)


def oauth_redirect_uri() -> str:
    return f"{get_settings().APP_PUBLIC_URL.rstrip('/')}/auth/google/callback"


def _ticket_secret() -> bytes:
    settings = get_settings()
    key = settings.GOOGLE_CLIENT_SECRET or settings.DISCORD_BOT_TOKEN
    return key.encode("utf-8")


def _owner_user_id() -> str:
    return get_settings().owner_user_id


def _pkce_verifier() -> str:
    return secrets.token_urlsafe(64).rstrip("=")


def issue_connect_ticket(*, slack_user_id: str | None = None) -> str:
    user_id = slack_user_id or _owner_user_id()
    payload = (
        f"{int(time.time()) + TICKET_TTL_SECONDS}:{user_id}:"
        f"{secrets.token_urlsafe(12)}:{_pkce_verifier()}"
    )
    sig = hmac.new(_ticket_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    raw = f"{payload}:{sig}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def parse_connect_ticket(ticket: str) -> ConnectTicket:
    padded = ticket + "=" * (-len(ticket) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise GoogleOAuthInvalidTicket() from exc
    payload, sep, sig = raw.rpartition(":")
    if not sep or not payload or not sig:
        raise GoogleOAuthInvalidTicket()
    expected = hmac.new(_ticket_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise GoogleOAuthInvalidTicket()
    exp_s, sep_user, rest = payload.partition(":")
    slack_user_id, sep_nonce, rest = rest.partition(":")
    _nonce, sep_verifier, code_verifier = rest.partition(":")
    if not sep_user or not sep_nonce or not sep_verifier or not code_verifier:
        raise GoogleOAuthInvalidTicket()
    try:
        expires_at = int(exp_s)
    except ValueError as exc:
        raise GoogleOAuthInvalidTicket() from exc
    if expires_at < int(time.time()):
        raise GoogleOAuthInvalidTicket()
    if slack_user_id != _owner_user_id():
        raise GoogleOAuthInvalidTicket()
    return ConnectTicket(slack_user_id=slack_user_id, code_verifier=code_verifier)


def issue_connect_url(*, slack_user_id: str | None = None) -> str:
    if not oauth_is_configured():
        raise GoogleOAuthNotConfigured()
    ticket = issue_connect_ticket(slack_user_id=slack_user_id)
    base = get_settings().APP_PUBLIC_URL.rstrip("/")
    return f"{base}/auth/google?{urlencode({'ticket': ticket})}"


def connect_message_markdown(*, slack_user_id: str | None = None) -> str:
    url = issue_connect_url(slack_user_id=slack_user_id)
    return "\n".join(
        [
            "**Connect Google** for Gmail and Calendar. You can add more than one account "
            "(work, personal, …) — pick the account on Google's screen.",
            "",
            f"[Open Google sign-in]({url})",
            "",
            "This link expires in 20 minutes. Google may warn that the app is unverified — "
            "use Advanced → Go to cto-agent (or similar) → Allow. Come back here after you approve.",
        ]
    )


def is_google_connect_command(text: str) -> bool:
    cleaned = re.sub(r"<[^>]+>", " ", text or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower().rstrip(".!?")
    for prefix in _connect_prefixes:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
    return cleaned in CONNECT_COMMANDS


def naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _row_to_bundle(row: GoogleAccount) -> GoogleTokenBundle:
    return GoogleTokenBundle(
        slack_user_id=row.slack_user_id,
        email=row.email,
        refresh_token=row.refresh_token,
        access_token=row.access_token,
        token_expiry=row.token_expiry,
        scopes=row.scopes,
        id=str(row.id),
        label=row.label,
        is_default=bool(row.is_default),
    )


def _account_summary(row: GoogleAccount | GoogleTokenBundle) -> dict[str, object]:
    return {
        "id": str(row.id) if row.id else None,
        "email": row.email,
        "label": row.label,
        "is_default": bool(row.is_default),
    }


async def _row_by_selector(db: AsyncSession, account: str | None) -> GoogleAccount | None:
    text = (account or "").strip()
    if not text or text == _owner_user_id():
        row = await db.scalar(select(GoogleAccount).where(GoogleAccount.is_default.is_(True)))
        if row is not None:
            return row
        return await db.scalar(select(GoogleAccount).order_by(GoogleAccount.created_at.asc()))
    lowered = text.lower()
    by_email = await db.scalar(
        select(GoogleAccount).where(func.lower(GoogleAccount.email) == lowered)
    )
    if by_email is not None:
        return by_email
    by_label = await db.scalar(
        select(GoogleAccount).where(func.lower(GoogleAccount.label) == lowered)
    )
    if by_label is not None:
        return by_label
    try:
        from uuid import UUID

        return await db.get(GoogleAccount, UUID(text))
    except (ValueError, AttributeError, TypeError):
        return None


async def load_account(
    account: str | None = None,
    session: AsyncSession | None = None,
    *,
    slack_user_id: str | None = None,
) -> GoogleTokenBundle | None:
    selector = account if account is not None else slack_user_id

    async def _load(db: AsyncSession) -> GoogleTokenBundle | None:
        row = await _row_by_selector(db, selector)
        return _row_to_bundle(row) if row else None

    if session is not None:
        return await _load(session)
    async with async_session_factory() as db:
        return await _load(db)


def load_account_sync(account: str | None = None) -> GoogleTokenBundle | None:
    return run_from_thread(load_account(account))


async def list_accounts() -> list[dict[str, object]]:
    async with async_session_factory() as db:
        rows = list(
            (await db.scalars(select(GoogleAccount).order_by(GoogleAccount.created_at.asc()))).all()
        )
        return [_account_summary(row) for row in rows]


def list_accounts_sync() -> list[dict[str, object]]:
    return run_from_thread(list_accounts())


async def _ensure_one_default(session: AsyncSession, prefer_id: object | None = None) -> None:
    if prefer_id is not None:
        await session.execute(update(GoogleAccount).values(is_default=False))
        row = await session.get(GoogleAccount, prefer_id)
        if row is not None:
            row.is_default = True
            return
    current = await session.scalar(select(GoogleAccount).where(GoogleAccount.is_default.is_(True)))
    if current is not None:
        return
    first = await session.scalar(select(GoogleAccount).order_by(GoogleAccount.created_at.asc()))
    if first is not None:
        first.is_default = True


async def upsert_google_account(
    *,
    slack_user_id: str,
    refresh_token: str | None,
    access_token: str | None,
    token_expiry: datetime | None,
    scopes: str | None,
    email: str | None,
    label: str | None = None,
) -> GoogleTokenBundle:
    now = _utcnow()
    async with async_session_factory() as session:
        row = None
        if email:
            row = await session.scalar(
                select(GoogleAccount).where(func.lower(GoogleAccount.email) == email.lower())
            )
        if row is None:
            if not refresh_token:
                raise ConfigError("Google did not return a refresh token; reconnect with consent.")
            count = int(await session.scalar(select(func.count()).select_from(GoogleAccount)) or 0)
            row = GoogleAccount(
                slack_user_id=slack_user_id,
                email=email,
                label=label,
                is_default=count == 0,
                refresh_token=refresh_token,
                access_token=access_token,
                token_expiry=naive_utc(token_expiry),
                scopes=scopes,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
        else:
            row.slack_user_id = slack_user_id
            if refresh_token:
                row.refresh_token = refresh_token
            if access_token:
                row.access_token = access_token
            if token_expiry is not None:
                row.token_expiry = naive_utc(token_expiry)
            if scopes:
                row.scopes = scopes
            if email:
                row.email = email
            if label:
                row.label = label
            row.updated_at = now
        await session.flush()
        await _ensure_one_default(session)
        await session.commit()
        await session.refresh(row)
        return _row_to_bundle(row)


def save_tokens_sync(
    *,
    refresh_token: str | None,
    access_token: str | None,
    token_expiry: datetime | None,
    scopes: str | None,
    email: str | None = None,
) -> None:
    settings = get_settings()
    run_from_thread(
        upsert_google_account(
            slack_user_id=settings.owner_user_id,
            refresh_token=refresh_token,
            access_token=access_token,
            token_expiry=token_expiry,
            scopes=scopes,
            email=email,
        )
    )


async def set_default_account(account: str) -> GoogleTokenBundle:
    async with async_session_factory() as session:
        row = await _row_by_selector(session, account)
        if row is None:
            raise ConfigError(f"No Google account matches {account!r}")
        await _ensure_one_default(session, prefer_id=row.id)
        await session.commit()
        await session.refresh(row)
        return _row_to_bundle(row)


async def label_account(account: str, label: str | None) -> GoogleTokenBundle:
    text = (label or "").strip() or None
    async with async_session_factory() as session:
        row = await _row_by_selector(session, account)
        if row is None:
            raise ConfigError(f"No Google account matches {account!r}")
        row.label = text
        row.updated_at = _utcnow()
        await session.commit()
        await session.refresh(row)
        return _row_to_bundle(row)


async def delete_account(account: str | None = None, *, slack_user_id: str | None = None) -> bool:
    selector = account if account is not None else slack_user_id
    async with async_session_factory() as session:
        row = await _row_by_selector(session, selector)
        if row is None:
            return False
        await session.delete(row)
        await session.flush()
        await _ensure_one_default(session)
        await session.commit()
        return True


def delete_account_sync(account: str | None = None) -> None:
    run_from_thread(delete_account(account))


def mark_env_refresh_rejected() -> None:
    global _env_refresh_rejected
    _env_refresh_rejected = True


def env_refresh_rejected() -> bool:
    return _env_refresh_rejected


def is_google_connected() -> bool:
    if load_account_sync() is not None:
        return True
    if _env_refresh_rejected:
        return False
    settings = get_settings()
    return bool(
        settings.GOOGLE_REFRESH_TOKEN
        and settings.GOOGLE_CLIENT_ID
        and settings.GOOGLE_CLIENT_SECRET
    )


def reconnect_config_error() -> ConfigError:
    settings = get_settings()
    if not oauth_is_configured():
        return ConfigError(
            "Google OAuth is not configured (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET)."
        )
    url = issue_connect_url()
    return ConfigError(
        "Google access is missing or expired. Ask the user to open this connect link: "
        f"{url} (or tell them to say “connect google” in Discord). "
        f"Configured Discord user: {settings.DISCORD_USER_ID}."
    )


def _client_config() -> dict[str, object]:
    settings = get_settings()
    return {
        "web": {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [oauth_redirect_uri()],
        }
    }


def _oauth_flow(*, state: str | None = None, code_verifier: str | None = None):
    from google_auth_oauthlib.flow import Flow

    return Flow.from_client_config(
        _client_config(),
        scopes=list(SCOPES),
        redirect_uri=oauth_redirect_uri(),
        state=state,
        autogenerate_code_verifier=False,
        code_verifier=code_verifier,
    )


def authorization_url(ticket: str) -> str:
    if not oauth_is_configured():
        raise GoogleOAuthNotConfigured()
    parsed = parse_connect_ticket(ticket)
    flow = _oauth_flow(code_verifier=parsed.code_verifier)
    url, _state = flow.authorization_url(
        access_type="offline",
        prompt="consent select_account",
        state=ticket,
    )
    return url


def exchange_code(code: str, ticket: str) -> GoogleTokenBundle:
    import os

    parsed = parse_connect_ticket(ticket)
    flow = _oauth_flow(state=ticket, code_verifier=parsed.code_verifier)
    os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
    flow.fetch_token(code=code)
    creds = flow.credentials
    return GoogleTokenBundle(
        slack_user_id=parsed.slack_user_id,
        email=_email_from_credentials(creds),
        refresh_token=creds.refresh_token or "",
        access_token=creds.token,
        token_expiry=naive_utc(creds.expiry),
        scopes=" ".join(creds.scopes or SCOPES),
    )


def _email_from_id_token(id_token: str) -> str | None:
    try:
        payload = id_token.split(".")[1]
        padded = payload + "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded))
        email = data.get("email")
        return email if isinstance(email, str) else None
    except Exception:
        return None


def _email_from_credentials(creds: object) -> str | None:
    id_token = getattr(creds, "id_token", None)
    if isinstance(id_token, dict):
        email = id_token.get("email")
        if isinstance(email, str) and email:
            return email
    if isinstance(id_token, str) and id_token:
        email = _email_from_id_token(id_token)
        if email:
            return email
    try:
        from googleapiclient.discovery import build

        info = (
            build("oauth2", "v2", credentials=creds, cache_discovery=False)
            .userinfo()
            .get()
            .execute()
        )
        email = info.get("email")
        return email if isinstance(email, str) else None
    except Exception:
        logger.exception("failed to fetch Google userinfo")
        return None


def handle_invalid_grant(account: str | None = None) -> None:
    try:
        delete_account_sync(account)
    except Exception:
        logger.exception("failed to delete Google account after invalid_grant")
    if not list_accounts_sync():
        mark_env_refresh_rejected()
