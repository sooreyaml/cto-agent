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
_creds: Credentials | None = None


def invalidate_google_credentials() -> None:
    global _creds
    with _lock:
        _creds = None


class PersistingCredentials(Credentials):
    def refresh(self, request: GoogleAuthRequest) -> None:  # type: ignore[override]
        super().refresh(request)
        try:
            save_tokens_sync(
                refresh_token=self.refresh_token,
                access_token=self.token,
                token_expiry=self.expiry,
                scopes=" ".join(self.scopes) if self.scopes else None,
            )
        except Exception:
            logger.exception("failed to persist Google tokens after refresh")


def _is_revoked(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "invalid_grant" in text or "revoked" in text or "invalid_rapt" in text


def _from_bundle(bundle: GoogleTokenBundle) -> PersistingCredentials:
    settings = get_settings()
    scopes = bundle.scopes.split() if bundle.scopes else list(SCOPES)
    return PersistingCredentials(
        token=bundle.access_token,
        refresh_token=bundle.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=scopes,
        expiry=bundle.token_expiry,
    )


def _from_env() -> PersistingCredentials:
    settings = get_settings()
    return PersistingCredentials(
        token=None,
        refresh_token=settings.GOOGLE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=list(SCOPES),
    )


def _credentials() -> Credentials:
    global _creds
    if not oauth_is_configured():
        raise ConfigError(
            "Google OAuth is not configured (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET)."
        )
    with _lock:
        if _creds is not None and _creds.refresh_token:
            creds = _creds
        else:
            creds = None
    if creds is None:
        bundle = load_account_sync()
        if bundle is not None:
            creds = _from_bundle(bundle)
        elif get_settings().GOOGLE_REFRESH_TOKEN and not env_refresh_rejected():
            creds = _from_env()
        else:
            raise reconnect_config_error()
        with _lock:
            _creds = creds
    if creds.valid:
        return creds
    if not creds.refresh_token:
        raise reconnect_config_error()
    try:
        creds.refresh(GoogleAuthRequest())
    except RefreshError as exc:
        if _is_revoked(exc):
            handle_invalid_grant()
            invalidate_google_credentials()
            raise reconnect_config_error() from exc
        raise
    return creds


def get_gmail():
    return build("gmail", "v1", credentials=_credentials(), cache_discovery=False)


def get_calendar():
    return build("calendar", "v3", credentials=_credentials(), cache_discovery=False)
