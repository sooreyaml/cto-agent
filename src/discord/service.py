import logging
import re
from contextlib import asynccontextmanager
from typing import Any

from src.agent.loop import run_agent
from src.config import get_settings
from src.discord.files import fetch_discord_image_data_urls
from src.discord.format import split_discord_sections
from src.google.service import (
    connect_message_markdown,
    is_google_connect_command,
    oauth_is_configured,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _noop_typing():
    yield


def _has_image_attachments(attachments: list[Any] | None) -> bool:
    for attachment in attachments or []:
        content_type = str(getattr(attachment, "content_type", "") or "")
        if content_type.startswith("image/"):
            return True
        filename = str(getattr(attachment, "filename", "") or "").lower()
        if filename.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
            return True
    return False


def _is_direct_message(message: Any) -> bool:
    return getattr(message, "guild", None) is None


def _mentions_bot(message: Any, bot_user_id: int) -> bool:
    return any(getattr(user, "id", None) == bot_user_id for user in (message.mentions or []))


def _clean_content(content: str, bot_user_id: int) -> str:
    return re.sub(rf"<@!?{bot_user_id}>", "", content or "").strip()


def _public_error(err: BaseException) -> str:
    text = str(err)
    if "111" in text or "Connection refused" in text:
        return (
            "Postgres connection refused. Set DATABASE_URL to the Coolify database "
            "*internal* URL (service hostname, port 5432). localhost inside the "
            "container is the app itself, not Postgres."
        )
    return text


async def handle_message(message: Any, *, bot_user_id: int) -> None:
    author = getattr(message, "author", None)
    if author is None:
        logger.info("skip discord message: missing author")
        return
    if getattr(author, "bot", False):
        logger.info("skip discord message: bot author")
        return
    if not _is_direct_message(message) and not _mentions_bot(message, bot_user_id):
        logger.info("skip discord message: not a DM or mention")
        return

    settings = get_settings()
    author_id = str(author.id)
    channel = message.channel
    if author_id != settings.DISCORD_USER_ID:
        logger.info("skip discord message: unauthorized user=%s", author_id)
        if _is_direct_message(message):
            try:
                await channel.send("This agent only responds to its configured Discord user.")
            except Exception:
                logger.exception("failed to reject unauthorized discord DM")
        return

    user_message = _clean_content(message.content or "", bot_user_id)
    attachments = list(message.attachments or [])
    may_have_images = _has_image_attachments(attachments)
    if not user_message and not may_have_images:
        return

    image_data_urls = await fetch_discord_image_data_urls(attachments)
    if not user_message and not image_data_urls:
        return

    if user_message and is_google_connect_command(user_message):
        if not oauth_is_configured():
            await channel.send(
                "Google OAuth is not configured. Set GOOGLE_CLIENT_ID and "
                "GOOGLE_CLIENT_SECRET, then try again."
            )
            return
        await channel.send(connect_message_markdown())
        return

    try:
        await message.add_reaction("👀")
        typing = getattr(channel, "typing", None)
        async with typing() if typing is not None else _noop_typing():  # noqa: SIM222
            result = await run_agent(
                channel_id=f"discord:{channel.id}",
                slack_user_id=author_id,
                user_message=user_message,
                image_data_urls=image_data_urls or None,
                surface="discord",
            )
        text = (result.get("text") or "").strip() or "Done."
        for chunk in split_discord_sections(text):
            await channel.send(chunk)
        await message.add_reaction("✅")
    except Exception as err:
        logger.exception("discord agent handler failed")
        try:
            await channel.send(f"⚠️ Something broke: {_public_error(err)}")
        except Exception:
            pass
