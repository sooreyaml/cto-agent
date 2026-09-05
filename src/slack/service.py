import logging

from src.agent.loop import run_agent
from src.config import get_settings
from src.google.service import (
    connect_message_mrkdwn,
    is_google_connect_command,
    oauth_is_configured,
)
from src.slack.client import post_channel_message, slack
from src.slack.files import fetch_slack_image_data_urls
from src.slack.schemas import SlackCallbackBody, SlackEvent, SlackFile

logger = logging.getLogger(__name__)


def _has_image_files(files: list[SlackFile]) -> bool:
    return any(f.mimetype and f.mimetype.startswith("image/") for f in files)


def _is_direct_message(event: SlackEvent) -> bool:
    if event.channel_type == "im":
        return True
    return bool(event.channel and event.channel.startswith("D"))


async def handle_event(body: SlackCallbackBody) -> None:
    event = body.event
    if not event:
        logger.info("skip slack event: missing event object")
        return
    if event.type != "message":
        logger.info("skip slack event: type=%s", event.type)
        return
    if event.bot_id or event.subtype in {"bot_message", "message_changed"}:
        logger.info("skip slack event: bot/subtype=%s", event.subtype)
        return
    if not _is_direct_message(event):
        logger.info(
            "skip slack event: not a DM channel=%s channel_type=%s",
            event.channel,
            event.channel_type,
        )
        return
    if not event.user:
        logger.info("skip slack event: no user")
        return

    user_message = event.text or ""
    file_dicts = [f.model_dump() for f in (event.files or [])]
    may_have_images = _has_image_files(event.files or [])
    if not user_message.strip() and not may_have_images:
        return

    image_data_urls = await fetch_slack_image_data_urls(file_dicts)
    if not user_message.strip() and not image_data_urls:
        return

    if user_message.strip() and is_google_connect_command(user_message):
        settings = get_settings()
        if event.user != settings.SLACK_USER_ID:
            await post_channel_message(
                event.channel or "",
                "This agent can only connect Google for its configured Slack user.",
            )
            return
        if not oauth_is_configured():
            await post_channel_message(
                event.channel or "",
                "Google OAuth is not configured. Set GOOGLE_CLIENT_ID and "
                "GOOGLE_CLIENT_SECRET, then try again.",
            )
            return
        await post_channel_message(event.channel or "", connect_message_mrkdwn(), mrkdwn=True)
        return

    try:
        await slack.reactions_add(
            channel=event.channel,
            timestamp=event.ts,
            name="eyes",
        )
        result = await run_agent(
            channel_id=event.channel or "",
            slack_user_id=event.user,
            user_message=user_message,
            image_data_urls=image_data_urls or None,
        )
        await post_channel_message(
            event.channel or "",
            result["text"],
            mrkdwn=True,
            thread_ts=event.thread_ts,
        )
        await slack.reactions_add(
            channel=event.channel,
            timestamp=event.ts,
            name="white_check_mark",
        )
    except Exception as err:
        logger.exception("agent handler failed")
        if event.channel:
            try:
                await slack.chat_postMessage(
                    channel=event.channel,
                    text=f":warning: Something broke: {_public_error(err)}",
                )
            except Exception:
                pass


def _public_error(err: BaseException) -> str:
    text = str(err)
    if "111" in text or "Connection refused" in text:
        return (
            "Postgres connection refused. Set DATABASE_URL to the Coolify database "
            "*internal* URL (service hostname, port 5432). localhost inside the "
            "container is the app itself, not Postgres."
        )
    return text
