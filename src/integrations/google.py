from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from src.config import get_settings
from src.exceptions import ConfigError

_creds: Credentials | None = None


def _credentials() -> Credentials:
    global _creds
    settings = get_settings()
    if not (
        settings.GOOGLE_CLIENT_ID
        and settings.GOOGLE_CLIENT_SECRET
        and settings.GOOGLE_REFRESH_TOKEN
    ):
        raise ConfigError(
            "Google OAuth not configured (GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN)"
        )
    if _creds is None:
        _creds = Credentials(
            token=None,
            refresh_token=settings.GOOGLE_REFRESH_TOKEN,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.GOOGLE_CLIENT_ID,
            client_secret=settings.GOOGLE_CLIENT_SECRET,
        )
    return _creds


def get_gmail():
    return build("gmail", "v1", credentials=_credentials(), cache_discovery=False)


def get_calendar():
    return build("calendar", "v3", credentials=_credentials(), cache_discovery=False)
