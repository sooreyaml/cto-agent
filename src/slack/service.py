import asyncio
import logging

from src.agent.loop import run_agent
from src.slack.client import post_channel_message, slack
from src.slack.files import fetch_slack_image_data_urls
from src.slack.schemas import SlackCallbackBody, SlackFile

logger = logging.getLogger(__name__)


def dispatch_detached(label: str, work) -> None:
    task = asyncio.create_task(work())

    def _on_done(done: asyncio.Task) -> None:
        if done.cancelled():
            return
        err = done.exception()
        if err:
            logger.error("background task failed label=%s", label, exc_info=err)

    task.add_done_callback(_on_done)


def _has_image_files(files: list[SlackFile]) -> bool:
    return any(f.mimetype and f.mimetype.startswith("image/") for f in files)


async def handle_event(body: SlackCallbackBody) -> None:
    event = body.event
    if (
        not event
        or event.type != "message"
        or event.bot_id
        or event.subtype in {"bot_message", "message_changed"}
        or event.channel_type != "im"
        or not event.user
    ):
        return

    user_message = event.text or ""
    file_dicts = [f.model_dump() for f in event.files]
    may_have_images = _has_image_files(event.files)
    if not user_message.strip() and not may_have_images:
        return

    image_data_urls = await fetch_slack_image_data_urls(file_dicts)
    if not user_message.strip() and not image_data_urls:
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
                    text=f":warning: Something broke: {err}",
                )
            except Exception:
                pass
