import hashlib
import hmac
import time

from slack_sdk.web.async_client import AsyncWebClient

from src.config import get_settings

settings = get_settings()
slack = AsyncWebClient(token=settings.SLACK_BOT_TOKEN)


def split_mrkdwn_sections(body: str, max_len: int = 2800) -> list[str]:
    text = body.strip()
    if len(text) <= max_len:
        return [text]
    parts: list[str] = []
    rest = text
    while rest:
        if len(rest) <= max_len:
            parts.append(rest)
            break
        cut = rest.rfind("\n\n", 0, max_len)
        if cut < max_len * 0.4:
            cut = rest.rfind("\n", 0, max_len)
        if cut < max_len * 0.3:
            cut = max_len
        parts.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    return parts


async def post_channel_message(
    channel: str,
    text: str,
    *,
    mrkdwn: bool = False,
    thread_ts: str | None = None,
) -> None:
    if mrkdwn:
        chunks = split_mrkdwn_sections(text)
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": chunk}} for chunk in chunks
        ]
        fallback = "".join(c for c in "\n\n".join(chunks) if c not in "*_`<>")[:400]
        await slack.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=fallback or "CTO Agent",
            blocks=blocks,
        )
        return
    await slack.chat_postMessage(channel=channel, text=text, thread_ts=thread_ts)


async def post_dm_to_user(user_id: str, text: str, *, mrkdwn: bool = False) -> None:
    opened = await slack.conversations_open(users=user_id)
    channel = (opened.get("channel") or {}).get("id")
    if not channel:
        raise RuntimeError("Could not open Slack DM channel")
    await post_channel_message(channel, text, mrkdwn=mrkdwn)


def verify_slack_signature(
    raw_body: str,
    timestamp: str | None,
    signature: str | None,
) -> tuple[bool, str]:
    if not timestamp or not signature:
        return False, "missing_headers"
    try:
        ts = int(timestamp)
    except ValueError:
        return False, "bad_timestamp"
    if abs(int(time.time()) - ts) > 300:
        return False, "timestamp_expired"
    basestring = f"v0:{timestamp}:{raw_body}"
    digest = hmac.new(
        settings.SLACK_SIGNING_SECRET.encode("utf-8"),
        basestring.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    my_sig = f"v0={digest}"
    try:
        valid = hmac.compare_digest(my_sig, signature)
    except Exception:
        return False, "length_mismatch"
    return valid, "ok" if valid else "signature_mismatch"
