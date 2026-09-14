import logging

from src.agent.codex_oauth import connect_message_markdown as openai_connect_message
from src.agent.codex_oauth import spawn_login_poll, start_device_auth
from src.agent.loop import run_agent
from src.config import get_settings
from src.connections.commands import match_connect_command
from src.connections.github_oauth import issue_connect_url as github_connect_url
from src.connections.github_oauth import oauth_is_configured as github_oauth_is_configured
from src.connections.granola_oauth import issue_connect_url as granola_connect_url
from src.google.service import issue_connect_url as google_connect_url
from src.google.service import oauth_is_configured as google_oauth_is_configured
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


def _slack_link(url: str, label: str) -> str:
    return f"<{url}|{label}>"


def _google_connect_mrkdwn(*, slack_user_id: str) -> str:
    url = google_connect_url(slack_user_id=slack_user_id)
    return "\n".join(
        [
            "*Connect Google* for Gmail and Calendar. You can add more than one account "
            "(work, personal, …) — pick the account on Google's screen.",
            "",
            _slack_link(url, "Open Google sign-in"),
            "",
            "This link expires in 20 minutes. Google may warn that the app is unverified — "
            "use Advanced → Go to cto-agent (or similar) → Allow. Come back here after you approve.",
        ]
    )


def _github_connect_mrkdwn(*, slack_user_id: str) -> str:
    url = github_connect_url(slack_user_id=slack_user_id)
    return "\n".join(
        [
            "*Connect GitHub* so I can read repos, PRs, and CI, and open issues.",
            "",
            _slack_link(url, "Open GitHub sign-in"),
            "",
            "This link expires in 20 minutes. Come back here after you approve.",
        ]
    )


def _granola_connect_mrkdwn(*, slack_user_id: str) -> str:
    url = granola_connect_url(slack_user_id=slack_user_id)
    return "\n".join(
        [
            "*Connect Granola* so I can read your meeting notes. Sign in in the browser — "
            "no API key.",
            "",
            _slack_link(url, "Open Granola sign-in"),
            "",
            "This link expires in 20 minutes. Come back here after you approve.",
        ]
    )


def _openai_connect_mrkdwn(pending: object) -> str:
    markdown = openai_connect_message(pending)
    # Device-auth messages already include a URL; keep plain text for Slack.
    return markdown.replace("**", "*")


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

    settings = get_settings()
    if event.user != settings.SLACK_USER_ID:
        logger.info("skip slack event: unauthorized user=%s", event.user)
        if event.channel:
            await post_channel_message(
                event.channel,
                "This agent only responds to its configured Slack user.",
            )
        return

    user_message = event.text or ""
    file_dicts = [f.model_dump() for f in (event.files or [])]
    may_have_images = _has_image_files(event.files or [])
    if not user_message.strip() and not may_have_images:
        return

    image_data_urls = await fetch_slack_image_data_urls(file_dicts)
    if not user_message.strip() and not image_data_urls:
        return

    channel = event.channel or ""
    if user_message.strip():
        connect = match_connect_command(user_message)
        if connect == "google":
            if not google_oauth_is_configured():
                await post_channel_message(
                    channel,
                    "Google OAuth is not configured. Set GOOGLE_CLIENT_ID and "
                    "GOOGLE_CLIENT_SECRET, then try again.",
                )
                return
            await post_channel_message(
                channel,
                _google_connect_mrkdwn(slack_user_id=event.user),
                mrkdwn=True,
            )
            return
        if connect == "github":
            if not github_oauth_is_configured():
                await post_channel_message(
                    channel,
                    "GitHub OAuth is not configured. Create a GitHub OAuth App, set "
                    "GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET, add callback "
                    f"{settings.APP_PUBLIC_URL.rstrip('/')}/auth/github/callback, "
                    "then try again.",
                )
                return
            await post_channel_message(
                channel,
                _github_connect_mrkdwn(slack_user_id=event.user),
                mrkdwn=True,
            )
            return
        if connect == "granola":
            await post_channel_message(
                channel,
                _granola_connect_mrkdwn(slack_user_id=event.user),
                mrkdwn=True,
            )
            return
        if connect == "openai-codex":
            pending = await start_device_auth()
            await post_channel_message(
                channel,
                _openai_connect_mrkdwn(pending),
                mrkdwn=True,
            )

            async def _done(_cred: object) -> None:
                await post_channel_message(
                    channel,
                    "ChatGPT / Codex is connected. OpenRouter stays primary; I will fall "
                    "back to your subscription if OpenRouter fails.",
                )

            async def _failed(err: BaseException) -> None:
                await post_channel_message(
                    channel,
                    f":warning: Codex login failed: {_public_error(err)}",
                )

            spawn_login_poll(pending, _done, _failed)
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
            surface="slack",
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
