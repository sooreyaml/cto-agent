import base64
from email.mime.text import MIMEText
from typing import Any

from fastapi.concurrency import run_in_threadpool

from src.integrations.google import get_gmail

USER_ID = "me"


def _encode_raw(to: str, subject: str, body: str) -> str:
    message = MIMEText(body, _charset="utf-8")
    message["To"] = to if "<" in to else f"<{to}>"
    message["Subject"] = subject
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")


def _header(headers: list[dict[str, Any]], name: str) -> str | None:
    for header in headers:
        if (header.get("name") or "").lower() == name.lower():
            return header.get("value")
    return None


def _extract_plain(part: dict[str, Any] | None) -> str:
    if not part:
        return ""
    body = ""
    if part.get("mimeType") == "text/plain" and (part.get("body") or {}).get("data"):
        raw = part["body"]["data"]
        padded = raw + "=" * (-len(raw) % 4)
        body += base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
    for child in part.get("parts") or []:
        body += _extract_plain(child)
    return body


def _search_sync(query: str, max_results: int) -> list[dict[str, Any]]:
    gmail = get_gmail()
    listed = (
        gmail.users().messages().list(userId=USER_ID, q=query, maxResults=max_results).execute()
    )
    ids = [m["id"] for m in listed.get("messages") or [] if m.get("id")]
    out: list[dict[str, Any]] = []
    for message_id in ids:
        msg = (
            gmail.users()
            .messages()
            .get(userId=USER_ID, id=message_id, format="metadata", metadataHeaders=["Subject"])
            .execute()
        )
        out.append(
            {
                "id": message_id,
                "threadId": msg.get("threadId"),
                "snippet": msg.get("snippet"),
                "subject": _header(msg.get("payload", {}).get("headers") or [], "Subject"),
            }
        )
    return out


def _get_sync(message_id: str, fmt: str) -> dict[str, Any]:
    gmail = get_gmail()
    msg = gmail.users().messages().get(userId=USER_ID, id=message_id, format=fmt).execute()
    headers = msg.get("payload", {}).get("headers") or []
    body = _extract_plain(msg.get("payload"))
    return {
        "id": msg.get("id"),
        "threadId": msg.get("threadId"),
        "snippet": msg.get("snippet"),
        "subject": _header(headers, "Subject"),
        "from": _header(headers, "From"),
        "body": body or msg.get("snippet"),
    }


def _draft_sync(to: str, subject: str, body: str) -> dict[str, Any]:
    gmail = get_gmail()
    draft = (
        gmail.users()
        .drafts()
        .create(userId=USER_ID, body={"message": {"raw": _encode_raw(to, subject, body)}})
        .execute()
    )
    message = draft.get("message") or {}
    return {
        "draftId": draft.get("id"),
        "messageId": message.get("id"),
        "threadId": message.get("threadId"),
    }


def _send_sync(to: str, subject: str, body: str) -> dict[str, Any]:
    gmail = get_gmail()
    sent = (
        gmail.users()
        .messages()
        .send(userId=USER_ID, body={"raw": _encode_raw(to, subject, body)})
        .execute()
    )
    return {
        "id": sent.get("id"),
        "threadId": sent.get("threadId"),
        "labelIds": sent.get("labelIds"),
    }


async def _search_messages(args: dict[str, Any]) -> list[dict[str, Any]]:
    max_results = min(max(args.get("max_results") or 10, 1), 20)
    return await run_in_threadpool(_search_sync, args["query"], max_results)


async def _get_message(args: dict[str, Any]) -> dict[str, Any]:
    return await run_in_threadpool(_get_sync, args["message_id"], args.get("format") or "full")


async def _create_draft(args: dict[str, Any]) -> dict[str, Any]:
    return await run_in_threadpool(_draft_sync, args["to"], args["subject"], args["body"])


async def _send_message(args: dict[str, Any]) -> dict[str, Any]:
    return await run_in_threadpool(_send_sync, args["to"], args["subject"], args["body"])


gmail_tools = {
    "gmail_search_messages": {
        "spec": {
            "type": "function",
            "function": {
                "name": "gmail_search_messages",
                "description": (
                    "Search Gmail with Gmail query syntax (e.g. is:unread, from:x, newer_than:7d). "
                    "Returns id, snippet, subject preview."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Gmail search query"},
                        "max_results": {"type": "integer", "description": "1–20, default 10"},
                    },
                    "required": ["query"],
                },
            },
        },
        "handler": _search_messages,
    },
    "gmail_get_message": {
        "spec": {
            "type": "function",
            "function": {
                "name": "gmail_get_message",
                "description": "Fetch a single Gmail message by id (snippet + plain text body if available).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message_id": {"type": "string"},
                        "format": {
                            "type": "string",
                            "enum": ["full", "metadata"],
                            "description": "Default full",
                        },
                    },
                    "required": ["message_id"],
                },
            },
        },
        "handler": _get_message,
    },
    "gmail_create_draft": {
        "spec": {
            "type": "function",
            "function": {
                "name": "gmail_create_draft",
                "description": "Create a draft email. Does not send.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "to": {"type": "string", "description": "Recipient email"},
                        "subject": {"type": "string"},
                        "body": {"type": "string", "description": "Plain text body"},
                    },
                    "required": ["to", "subject", "body"],
                },
            },
        },
        "handler": _create_draft,
    },
    "gmail_send_message": {
        "spec": {
            "type": "function",
            "function": {
                "name": "gmail_send_message",
                "description": (
                    "Send an email immediately (plain text). Use only after user explicitly confirms. "
                    "Uses configured Google account."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "to": {"type": "string"},
                        "subject": {"type": "string"},
                        "body": {"type": "string"},
                    },
                    "required": ["to", "subject", "body"],
                },
            },
        },
        "handler": _send_message,
    },
}
