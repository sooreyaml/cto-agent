import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.config import get_settings

logger = logging.getLogger(__name__)
CALENDAR_PLACEHOLDER = "{{CALENDAR_CONTEXT}}"
WORK_PLACEHOLDER = "{{WORK_CONTEXT}}"


def current_calendar_context() -> str:
    settings = get_settings()
    now = datetime.now(ZoneInfo(settings.TIMEZONE))
    long = now.strftime(f"%A, {now.day} %B {now.year}")
    iso = now.strftime("%Y-%m-%d")
    return (
        f"Today (authoritative for this chat turn, {settings.TIMEZONE}) is {long} "
        f"— calendar date **{iso}**. Use only this when the user asks about "
        '"today", weekends, or due dates; do not guess another year or day.'
    )


def fallback_system_template() -> str:
    return "\n".join(
        [
            "You are CTO Agent, a concise technical chief-of-staff assistant in Discord.",
            CALENDAR_PLACEHOLDER,
            WORK_PLACEHOLDER,
            "Prefer short answers; use bullets when listing items.",
            "Formatting: this text is shown in Discord. Use **bold**, *italic*, and [label](url).",
            "Do not use Slack <url|label> links.",
            "Work: use work_list / work_create / work_update for priorities, tasks, decisions, commitments.",
            "GitHub: github_list_repos lists repos the token can access (recently pushed first; active_days keeps only recent ones). github_search_issues searches PRs/issues across all of them (e.g. is:pr is:open involves:@me). Per-repo tools need owner and repo. Writes: github_create_issue, github_add_comment, github_merge_pull_request (merge only after explicit confirmation).",
            "Google: multiple accounts are supported. Use google_connect_link to add another; google_manage_account to list/label/default/disconnect. Gmail and Calendar take optional account (email or label).",
            "Connections: never tell the user to edit .env. Google, GitHub, and Granola use browser OAuth — connections_connect, or they say connect github / connect granola / connect google. Other tools: paste a key, then connections_save. Use connections_request for APIs without a native tool.",
            "Use tools when the user asks for live data. For destructive actions (send email, delete calendar events, merge a PR) require explicit confirmation first.",
            "If a tool is not connected, send the OAuth link (Google/GitHub/Granola) or ask for a key; do not mention .env.",
            "The user may attach images; describe what you see and use that context in your answer.",
        ]
    )


def load_system_template() -> str:
    settings = get_settings()
    raw = settings.SYSTEM_PROMPT_PATH.strip()
    resolved = Path(raw) if Path(raw).is_absolute() else Path.cwd() / raw
    try:
        return resolved.read_text(encoding="utf-8")
    except OSError:
        logger.warning("SYSTEM_PROMPT file missing; using built-in fallback path=%s", resolved)
        return fallback_system_template()


def build_system_prompt(*, surface: str = "discord", work_context: str = "") -> str:
    template = load_system_template()
    calendar = current_calendar_context()
    work = work_context.strip() or "Work board: (empty or unavailable)."
    if CALENDAR_PLACEHOLDER in template:
        text = template.replace(CALENDAR_PLACEHOLDER, calendar)
    else:
        text = f"{template.strip()}\n\n{calendar}"
    if WORK_PLACEHOLDER in text:
        text = text.replace(WORK_PLACEHOLDER, work)
    else:
        text = f"{text.strip()}\n\n{work}"
    return text.strip()
