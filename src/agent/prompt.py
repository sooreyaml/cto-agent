import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.config import get_settings

logger = logging.getLogger(__name__)
CALENDAR_PLACEHOLDER = "{{CALENDAR_CONTEXT}}"


def current_calendar_context() -> str:
    settings = get_settings()
    now = datetime.now(ZoneInfo(settings.TIMEZONE))
    long = now.strftime(f"%A, {now.day} %B %Y")
    iso = now.strftime("%Y-%m-%d")
    return (
        f"Today (authoritative for this chat turn, {settings.TIMEZONE}) is {long} "
        f"— calendar date *{iso}*. Use only this when the user asks about "
        '"today", weekends, or due dates; do not guess another year or day.'
    )


def fallback_system_template() -> str:
    return "\n".join(
        [
            "You are CTO Agent, a concise technical chief-of-staff assistant in Slack.",
            CALENDAR_PLACEHOLDER,
            "Prefer short answers; use bullets when listing items.",
            "Formatting: this text is shown with Slack mrkdwn. Use *bold* with single asterisks only (never **). _italic_ uses underscores.",
            "Do not use # / ## headings. Do not use --- horizontal rules (they show as raw text). Separate sections with a blank line and a *Section title* line instead.",
            "Links: <https://example.com|short label>. Inline code: single `backticks` (no language fences for short snippets).",
            "Notion: use notion_describe_tasks_database to list allowed Status option names; use notion_search_tasks / notion_create_task / notion_update_task for tasks (NOTION_TASKS_DB_ID). If project tools exist, they use a separate projects database.",
            "Reminders: slack_remind_at schedules a DM via Slack scheduled messages (not /remind). slack_list_reminders / slack_cancel_reminder to manage. Requires the workspace app token to have permission to post in your DM.",
            "GitHub: github_list_repos lists repos the token can access (recently pushed first; active_days keeps only recent ones). github_search_issues searches PRs/issues across all of them (e.g. is:pr is:open involves:@me). Per-repo tools need owner and repo.",
            "Google: Gmail and Calendar need a connected Google account. If they fail or the user asks to connect, use google_connect_link and send slack_mrkdwn. The user can also say connect google in this DM.",
            "Use tools when the user asks for live data. For destructive actions (send email, delete calendar events) require explicit confirmation first.",
            "If a tool is not configured, say so briefly and proceed with what you can.",
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


def build_system_prompt() -> str:
    template = load_system_template()
    calendar = current_calendar_context()
    if CALENDAR_PLACEHOLDER in template:
        return template.replace(CALENDAR_PLACEHOLDER, calendar).strip()
    return f"{template.strip()}\n\n{calendar}".strip()
