from typing import Annotated

from fastapi import Depends, Header

from src.config import Settings, get_settings
from src.cron.exceptions import CronNotConfigured, CronUnauthorized


async def require_cron_secret(
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    if not settings.CRON_SECRET:
        raise CronNotConfigured()
    if authorization != f"Bearer {settings.CRON_SECRET}":
        raise CronUnauthorized()


CronAuth = Annotated[None, Depends(require_cron_secret)]
