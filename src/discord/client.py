import asyncio
import logging

import discord
from src.config import get_settings
from src.discord.format import split_discord_sections
from src.discord.service import handle_message

logger = logging.getLogger(__name__)

_client: "DiscordAgentClient | None" = None
_task: asyncio.Task[None] | None = None


class DiscordAgentClient(discord.Client):
    async def on_ready(self) -> None:
        user = self.user
        logger.info(
            "discord connected bot=%s owner=%s",
            getattr(user, "id", None),
            get_settings().DISCORD_USER_ID,
        )

    async def on_message(self, message: discord.Message) -> None:
        if self.user is None:
            return
        await handle_message(message, bot_user_id=self.user.id)


def get_discord_client() -> DiscordAgentClient | None:
    return _client


async def post_discord_dm(user_id: str, text: str) -> None:
    client = get_discord_client()
    if client is None or not client.is_ready():
        raise RuntimeError("Discord bot is not connected")
    user = client.get_user(int(user_id)) or await client.fetch_user(int(user_id))
    channel = user.dm_channel or await user.create_dm()
    for chunk in split_discord_sections(text):
        await channel.send(chunk)


async def start_discord_bot() -> None:
    global _client, _task
    settings = get_settings()
    if _client is not None:
        return

    intents = discord.Intents.default()
    intents.message_content = True
    intents.dm_messages = True
    client = DiscordAgentClient(intents=intents)
    _client = client

    async def _run() -> None:
        try:
            await client.start(settings.DISCORD_BOT_TOKEN)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("discord bot stopped unexpectedly")

    _task = asyncio.create_task(_run(), name="discord-bot")
    for _ in range(60):
        if client.is_ready():
            break
        if _task.done():
            logger.error("discord bot failed to start")
            break
        await asyncio.sleep(0.5)
    else:
        logger.error("discord did not become ready within 30s")


async def stop_discord_bot() -> None:
    global _client, _task
    client = _client
    task = _task
    _client = None
    _task = None
    if client is not None and not client.is_closed():
        await client.close()
    if task is not None:
        try:
            await task
        except asyncio.CancelledError:
            pass
