from src.config import get_settings
from src.discord.client import post_discord_dm


async def notify_owner(text: str) -> None:
    settings = get_settings()
    await post_discord_dm(settings.DISCORD_USER_ID, text)
