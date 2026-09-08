import logging
import threading

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from src.config import get_settings
from src.exceptions import ConfigError
from src.google.constants import SCOPES
from src.google.service import (
    GoogleTokenBundle,
    env_refresh_rejected,
    handle_invalid_grant,
    load_account_sync,
    oauth_is_configured,
    reconnect_config_error,
    save_tokens_sync,
)

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_creds_by_key: dict[str, Credentials] = {}


def invalidate_google_credentials(key: str | None = None) -> None:
    with _lock:
        if key is None:
            _creds_by_key.clear()
        else:
            _creds_by_key.pop(key.lower(), None)


class PersistingCredentials(Credentials):
    account_email: str | None = None
    cache_key: str = "default"

    def refresh(self, request: GoogleAuthRequest) -> None:  # type: ignore[override]
        super().refresh(request)
        try:
            save_tokens_sync(
                refresh_token=self.refresh_token,
                access_token=self.token,
                token_expiry=self.expiry,
                scopes=" ".join(self.scopes) if self.scopes else None,
                email=self.account_email,
            )
        except Exception:
            logger.exception("failed to persist Google tokens after refresh")


def _is_revoked(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "invalid_grant" in text or "revoked" in text or "invalid_rapt" in text


def _from_bundle(bundle: GoogleTokenBundle) -> PersistingCredentials:
    settings = get_settings()
    scopes = bundle.scopes.split() if bundle.scopes else list(SCOPES)
    creds = PersistingCredentials(
        token=bundle.access_token,
        refresh_token=bundle.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=scopes,
        expiry=bundle.token_expiry,
    )
    creds.account_email = bundle.email
    creds.cache_key = bundle.key
    return creds


def _from_env() -> PersistingCredentials:
    settings = get_settings()
    creds = PersistingCredentials(
        token=None,
        refresh_token=settings.GOOGLE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=list(SCOPES),
    )
    creds.account_email = settings.GOOGLE_USER_EMAIL or None
    creds.cache_key = (settings.GOOGLE_USER_EMAIL or "env").lower()
    return creds


def _credentials(account: str | None = None) -> Credentials:
    if not oauth_is_configured():
        raise ConfigError(
            "Google OAuth is not configured (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET)."
        )
    bundle = load_account_sync(account)
    cache_key = (account or (bundle.key if bundle else "default")).lower()
    with _lock:
        creds = _creds_by_key.get(cache_key)
    if creds is None:
        if bundle is not None:
            creds = _from_bundle(bundle)
            cache_key = bundle.key
        elif not account and get_settings().GOOGLE_REFRESH_TOKEN and not env_refresh_rejected():
            creds = _from_env()
            cache_key = creds.cache_key
        else:
            raise reconnect_config_error()
        with _lock:
            _creds_by_key[cache_key] = creds
    if creds.valid:
        return creds
    if not creds.refresh_token:
        raise reconnect_config_error()
    try:
        creds.refresh(GoogleAuthRequest())
    except RefreshError as exc:
        if _is_revoked(exc):
            handle_invalid_grant(creds.account_email or cache_key)
            invalidate_google_credentials(cache_key)
            raise reconnect_config_error() from exc
        raise
    return creds


def get_gmail(account: str | None = None):
    return build("gmail", "v1", credentials=_credentials(account), cache_discovery=False)


def get_calendar(account: str | None = None):
    return build("calendar", "v3", credentials=_credentials(account), cache_discovery=False)
