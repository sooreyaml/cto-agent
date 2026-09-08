import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi.concurrency import run_in_threadpool

from src.agent.llm import MODEL, llm
from src.config import get_settings
from src.connections.repository import resolve_token
from src.google.service import is_google_connected, list_accounts_sync
from src.integrations.github import github_client
from src.integrations.google import get_calendar, get_gmail
from src.integrations.granola import granola_request
from src.notify import notify_owner
from src.tools.github import fetch_active_repos
from src.work.repository import brief_bundle

logger = logging.getLogger(__name__)


async def _safe(label: str, fn) -> dict[str, Any]:
    try:
        data = await fn()
        return {"ok": True, "data": data}
    except Exception as err:
        logger.warning("daily brief source failed label=%s", label, exc_info=err)
        return {"ok": False, "error": str(err)}


async def _work() -> Any:
    return await brief_bundle()


def _google_account_keys() -> list[str | None]:
    accounts = list_accounts_sync()
    keys = [
        str(item.get("email") or item.get("id"))
        for item in accounts
        if item.get("email") or item.get("id")
    ]
    if keys:
        return keys
    if is_google_connected():
        return [None]
    return []


def _calendar_for(account: str | None) -> list[dict[str, Any]]:
    settings = get_settings()
    cal = get_calendar(account)
    tz = ZoneInfo(settings.TIMEZONE)
    start = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    res = (
        cal.events()
        .list(
            calendarId="primary",
            timeMin=start.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            timeZone=settings.TIMEZONE,
            maxResults=40,
        )
        .execute()
    )
    return [
        {
            "summary": event.get("summary"),
            "start": (event.get("start") or {}).get("dateTime")
            or (event.get("start") or {}).get("date"),
            "htmlLink": event.get("htmlLink"),
        }
        for event in res.get("items") or []
    ]


def _gmail_for(account: str | None) -> list[dict[str, Any]]:
    gmail = get_gmail(account)
    listed = (
        gmail.users()
        .messages()
        .list(userId="me", q="is:unread newer_than:7d", maxResults=8)
        .execute()
    )
    items: list[dict[str, Any]] = []
    for message in listed.get("messages") or []:
        message_id = message.get("id")
        if not message_id:
            continue
        msg = (
            gmail.users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format="metadata",
                metadataHeaders=["Subject", "From"],
            )
            .execute()
        )
        headers = msg.get("payload", {}).get("headers") or []
        subject = next(
            (h.get("value") for h in headers if (h.get("name") or "").lower() == "subject"), None
        )
        sender = next(
            (h.get("value") for h in headers if (h.get("name") or "").lower() == "from"), None
        )
        items.append({"subject": subject, "from": sender, "snippet": msg.get("snippet")})
    return items


def _calendar_sync() -> Any:
    keys = _google_account_keys()
    if not keys:
        return {"skipped": True}
    return [{"account": key or "default", "events": _calendar_for(key)} for key in keys]


def _gmail_sync() -> Any:
    keys = _google_account_keys()
    if not keys:
        return {"skipped": True}
    return [{"account": key or "default", "messages": _gmail_for(key)} for key in keys]


async def _repo_brief(client: Any, repo: dict[str, Any]) -> dict[str, Any]:
    owner = repo["owner"]
    name = repo["name"]
    entry: dict[str, Any] = {
        "repo": repo["full_name"],
        "pushed_at": repo.get("pushed_at"),
        "default_branch": repo.get("default_branch"),
    }
    try:
        prs = await client.get(
            f"/repos/{owner}/{name}/pulls",
            params={"state": "open", "per_page": 8},
        )
        prs.raise_for_status()
        entry["open_prs"] = [
            {"title": pr.get("title"), "url": pr.get("html_url")} for pr in prs.json()
        ]
    except Exception as err:
        entry["open_prs_error"] = str(err)
    try:
        runs = await client.get(
            f"/repos/{owner}/{name}/actions/runs",
            params={"branch": repo.get("default_branch") or "main", "per_page": 8},
        )
        runs.raise_for_status()
        failing = [
            run
            for run in (runs.json().get("workflow_runs") or [])
            if run.get("conclusion") == "failure"
        ]
        entry["recent_failed_runs"] = [
            {"name": run.get("name"), "url": run.get("html_url")} for run in failing[:4]
        ]
    except Exception as err:
        entry["ci_error"] = str(err)
    return entry


async def _github() -> Any:
    if not await resolve_token("github"):
        return {"skipped": True}
    async with github_client() as client:
        active = await fetch_active_repos(client)
        if not active:
            return []
        return list(await asyncio.gather(*[_repo_brief(client, repo) for repo in active]))


async def _granola() -> Any:
    if not await resolve_token("granola"):
        return {"skipped": True}
    return await granola_request("/meetings?limit=5")


async def run_daily_brief() -> None:
    settings = get_settings()
    work_part = await _safe("work", _work)
    calendar_part = await _safe("calendar", lambda: run_in_threadpool(_calendar_sync))
    gmail_part = await _safe("gmail", lambda: run_in_threadpool(_gmail_sync))
    github_part = await _safe("github", _github)
    granola_part = await _safe("granola", _granola)

    bundle = {
        "date": datetime.now(UTC).isoformat(),
        "timezone": settings.TIMEZONE,
        "work": work_part,
        "calendar": calendar_part,
        "gmail": gmail_part,
        "github": github_part,
        "granola": granola_part,
    }

    completion = await llm.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": " ".join(
                    [
                        "You write a short daily executive brief for Discord using Discord markdown.",
                        "Formatting rules: **bold**, *italic*, [label](url). Do not use Slack <url|label> links.",
                        "Start a section with a short bold line like **Today** or **Priorities** then bullet lines.",
                        "For links use [label](https://example.com) only when a URL is essential; do not paste bare long URLs.",
                        "Include sections only where you have data: **Today** (calendar), **Inbox** (Gmail), **Code** (GitHub — recently active repos), **Priorities**, **Tasks**, **Commitments**.",
                        "Calendar and Gmail data may be a list of {account, events|messages}. Label the account when more than one is present.",
                        "When work.data exists and work.ok: **Priorities** (rank, title, notes); **Tasks** (blocked and overdue first — title, status, due, project); **Commitments** (who, what, due).",
                        "Call out blocked or high-priority work first. Omit empty fields; keep each row to 1–3 lines.",
                        "If a source was skipped or errored, omit or one short line. Stay under ~800 words.",
                    ]
                ),
            },
            {"role": "user", "content": json.dumps(bundle, default=str)},
        ],
        temperature=0.35,
        max_tokens=2048,
    )
    text = (completion.choices[0].message.content or "").strip() if completion.choices else ""
    if not text:
        logger.error("daily brief: empty LLM output")
        return
    await notify_owner(text)
    logger.info("daily brief sent")
