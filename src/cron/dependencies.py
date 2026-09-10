import hmac
from typing import Annotated

from fastapi import Depends, Header

from src.config import Settings, get_settings
from src.cron.exceptions import CronNotConfigured, CronUnauthorized


def _equals(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def _token_from_authorization(authorization: str | None) -> str | None:
    token = (authorization or "").strip()
    if not token:
        return None
    if token[:7].lower() == "bearer ":
        token = token[7:].strip()
    return token or None


async def require_cron_secret(
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
    x_cron_secret: Annotated[str | None, Header()] = None,
) -> None:
    if not settings.CRON_SECRET:
        raise CronNotConfigured()
    provided = _token_from_authorization(authorization)
    header = (x_cron_secret or "").strip() or None
    if provided and _equals(provided, settings.CRON_SECRET):
        return
    if header and _equals(header, settings.CRON_SECRET):
        return
    raise CronUnauthorized()


CronAuth = Annotated[None, Depends(require_cron_secret)]
