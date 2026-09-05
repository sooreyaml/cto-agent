from notion_client import AsyncClient

from src.config import get_settings
from src.exceptions import ConfigError


def get_notion() -> AsyncClient:
    settings = get_settings()
    if not settings.NOTION_TOKEN:
        raise ConfigError("NOTION_TOKEN not configured")
    return AsyncClient(auth=settings.NOTION_TOKEN, notion_version="2022-06-28")
