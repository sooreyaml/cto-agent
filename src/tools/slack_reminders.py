import time
from datetime import UTC, datetime
from typing import Any

from src.config import get_settings
from src.slack.client import slack


async def _dm_channel_id(slack_user_id: str) -> str:
    opened = await slack.conversations_open(users=slack_user_id)
    channel = (opened.get("channel") or {}).get("id")
    if not channel:
        raise RuntimeError("Could not open Slack DM for reminder")
    return channel


def _resolve_post_at(args: dict[str, Any]) -> int:
    now = int(time.time())
    if args.get("in_minutes") is not None:
        return now + max(1, int(args["in_minutes"])) * 60
    if args.get("post_at_unix") is not None:
        return int(args["post_at_unix"])
    when_iso = (args.get("when_iso") or "").strip()
    if when_iso:
        parsed = datetime.fromisoformat(when_iso.replace("Z", "+00:00"))
        return int(parsed.timestamp())
    raise ValueError("Provide one of: in_minutes, post_at_unix, or when_iso")


def _assert_window(post_at: int) -> None:
    now = int(time.time())
    if post_at < now + 60:
        raise ValueError("Reminder must be at least 60 seconds from now (Slack limit)")
    if post_at > now + 120 * 24 * 60 * 60:
        raise ValueError("Reminder too far ahead (Slack allows up to about 120 days)")


async def _remind_at(args: dict[str, Any]) -> dict[str, Any]:
    uid = (args.get("slack_user_id") or get_settings().SLACK_USER_ID).strip()
    explicit = [
        v
        for v in (
            args.get("in_minutes"),
            args.get("post_at_unix"),
            (args.get("when_iso") or "").strip(),
        )
        if v not in (None, "")
    ]
    if len(explicit) != 1:
        raise ValueError("Provide exactly one of: in_minutes, post_at_unix, or when_iso")
    post_at = _resolve_post_at(args)
    _assert_window(post_at)
    channel = await _dm_channel_id(uid)
    res = await slack.chat_scheduleMessage(channel=channel, text=args["text"], post_at=post_at)
    if not res.get("ok"):
        raise RuntimeError(res.get("error") or "scheduleMessage failed")
    return {
        "ok": True,
        "scheduled_message_id": res.get("scheduled_message_id"),
        "channel": channel,
        "post_at": post_at,
        "post_at_iso": datetime.fromtimestamp(post_at, tz=UTC).isoformat(),
    }


async def _list_reminders(args: dict[str, Any]) -> dict[str, Any]:
    uid = (args.get("slack_user_id") or get_settings().SLACK_USER_ID).strip()
    channel = await _dm_channel_id(uid)
    res = await slack.chat_scheduledMessages_list(
        channel=channel,
        limit=min(args.get("limit") or 20, 100),
    )
    if not res.get("ok"):
        raise RuntimeError(res.get("error") or "scheduledMessages.list failed")
    return {
        "reminders": [
            {
                "scheduled_message_id": item.get("id"),
                "channel_id": item.get("channel_id"),
                "post_at": item.get("post_at"),
                "post_at_iso": (
                    datetime.fromtimestamp(item["post_at"], tz=UTC).isoformat()
                    if item.get("post_at") is not None
                    else None
                ),
                "date_created": item.get("date_created"),
                "text": item.get("text"),
            }
            for item in res.get("scheduled_messages") or []
        ]
    }


async def _cancel_reminder(args: dict[str, Any]) -> dict[str, Any]:
    channel = (args.get("channel_id") or "").strip() or await _dm_channel_id(
        (args.get("slack_user_id") or get_settings().SLACK_USER_ID).strip()
    )
    res = await slack.chat_deleteScheduledMessage(
        channel=channel,
        scheduled_message_id=args["scheduled_message_id"],
    )
    if not res.get("ok"):
        raise RuntimeError(res.get("error") or "deleteScheduledMessage failed")
    return {"ok": True}


slack_reminder_tools = {
    "slack_remind_at": {
        "spec": {
            "type": "function",
            "function": {
                "name": "slack_remind_at",
                "description": (
                    "Schedule a Slack DM to the user at a future time (scheduled message — needs chat:write). "
                    "Same UX as a reminder. Use NOTION/CTO Agent owner’s Slack user unless slack_user_id is set. "
                    "Provide exactly one of in_minutes, post_at_unix, or when_iso."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Reminder body (plain text)"},
                        "in_minutes": {
                            "type": "integer",
                            "description": "Send this many minutes from now",
                        },
                        "post_at_unix": {
                            "type": "integer",
                            "description": "Unix time in seconds when to send",
                        },
                        "when_iso": {
                            "type": "string",
                            "description": "ISO 8601 datetime (include offset or Z), e.g. 2026-07-27T18:00:00+01:00",
                        },
                        "slack_user_id": {
                            "type": "string",
                            "description": "Optional Slack member ID (U…). Defaults to configured owner.",
                        },
                    },
                    "required": ["text"],
                },
            },
        },
        "handler": _remind_at,
    },
    "slack_list_reminders": {
        "spec": {
            "type": "function",
            "function": {
                "name": "slack_list_reminders",
                "description": (
                    "List scheduled DM reminders for the bot→user DM (scheduled messages). "
                    "Optional slack_user_id for which user’s DM to inspect."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "slack_user_id": {
                            "type": "string",
                            "description": "Optional Slack member ID; defaults to configured owner",
                        },
                        "limit": {"type": "integer", "description": "Max items (default 20)"},
                    },
                },
            },
        },
        "handler": _list_reminders,
    },
    "slack_cancel_reminder": {
        "spec": {
            "type": "function",
            "function": {
                "name": "slack_cancel_reminder",
                "description": (
                    "Cancel a scheduled DM reminder. Use scheduled_message_id from slack_list_reminders; "
                    "channel_id must match that row (or pass slack_user_id to resolve the same DM)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "scheduled_message_id": {"type": "string"},
                        "channel_id": {
                            "type": "string",
                            "description": "DM channel ID from list; omit if slack_user_id is set (uses owner DM)",
                        },
                        "slack_user_id": {
                            "type": "string",
                            "description": "If channel_id omitted, open this user’s DM with the bot",
                        },
                    },
                    "required": ["scheduled_message_id"],
                },
            },
        },
        "handler": _cancel_reminder,
    },
}
