"""Deterministic capability routing for the agent.

The model should not receive every integration's tool schema for every turn.  The
router is intentionally conservative: a matched capability group enables all of
that group's tools, while an unrelated conversational turn receives no tools.
This keeps the fast path unchanged for the model, but makes tool availability
explicit and cheap to test before introducing an LLM-based planner.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from src.agent.registry import all_tools

TOOL_GROUPS: dict[str, frozenset[str]] = {
    "work": frozenset(
        {
            "work_list",
            "work_create",
            "work_update",
            "work_remind",
            "work_ingest_notes",
        }
    ),
    "memory": frozenset(
        {
            "memory_search",
            "memory_save",
            "memory_archive",
        }
    ),
    "github": frozenset(
        {
            "github_list_repos",
            "github_search_issues",
            "github_list_pull_requests",
            "github_get_branch_ci_status",
            "github_get_workflow_run",
            "github_get_workflow_run_jobs",
            "github_get_repository_readme",
            "github_list_open_issues",
            "github_get_path_contents",
            "github_create_issue",
            "github_add_comment",
            "github_merge_pull_request",
        }
    ),
    "gmail": frozenset(
        {
            "gmail_search_messages",
            "gmail_get_message",
            "gmail_create_draft",
            "gmail_send_message",
        }
    ),
    "calendar": frozenset(
        {
            "calendar_list_events",
            "calendar_get_event",
            "calendar_create_event",
            "calendar_update_event",
            "calendar_delete_event",
        }
    ),
    "google_accounts": frozenset(
        {
            "google_connect_link",
            "google_manage_account",
        }
    ),
    "granola": frozenset(
        {
            "granola_list_meetings",
            "granola_get_meeting",
            "granola_search",
        }
    ),
    "slack": frozenset(
        {
            "slack_remind_at",
            "slack_list_reminders",
            "slack_cancel_reminder",
        }
    ),
    "connections": frozenset(
        {
            "connections_catalog",
            "connections_connect",
            "connections_list",
            "connections_save",
            "connections_delete",
            "connections_request",
        }
    ),
}

UNIVERSAL_TOOLS = frozenset(
    {
        "connections_catalog",
        "connections_connect",
        "connections_list",
    }
)

_GROUP_KEYWORDS: dict[str, tuple[str, ...]] = {
    "work": (
        "priority",
        "priorities",
        "task",
        "tasks",
        "todo",
        "to-do",
        "commitment",
        "commitments",
        "decision",
        "decisions",
        "reminder",
        "remind",
        "work board",
        "blocked",
        "overdue",
        "deadline",
        "project",
    ),
    "memory": (
        "remember",
        "memory",
        "forget",
        "previously",
        "preference",
        "preferences",
        "my default",
        "we agreed",
        "what did we decide",
    ),
    "github": (
        "github",
        "repo",
        "repository",
        "pull request",
        "pr",
        "issue",
        "ci",
        "actions",
        "workflow",
        "branch",
        "commit",
        "code",
    ),
    "gmail": (
        "gmail",
        "email",
        "inbox",
        "mail",
    ),
    "calendar": (
        "calendar",
        "event",
        "schedule",
        "availability",
        "meeting",
    ),
    "google_accounts": (
        "google",
        "google account",
    ),
    "granola": (
        "granola",
        "meeting notes",
        "transcript",
        "meeting transcript",
    ),
    "slack": ("slack",),
    "connections": (
        "connect",
        "reconnect",
        "integration",
        "integrations",
        "oauth",
        "api key",
        "token",
        "connected account",
    ),
}


def _matches_keyword(text: str, keyword: str) -> bool:
    """Match a word or phrase without matching substrings such as ``pr`` in ``priority``."""

    pattern = r"(?<![a-z0-9])" + re.escape(keyword) + r"(?![a-z0-9])"
    return re.search(pattern, text) is not None


def matched_groups(user_message: str) -> set[str]:
    text = " ".join((user_message or "").lower().split())
    return {
        group
        for group, keywords in _GROUP_KEYWORDS.items()
        if any(_matches_keyword(text, keyword) for keyword in keywords)
    }


def tool_names_for_message(
    user_message: str,
    *,
    available_names: Iterable[str] | None = None,
) -> list[str]:
    """Return the tools relevant to a turn in stable, registry order.

    For a confident capability match, only that capability and the small
    connection-management set are exposed.  Ambiguous text falls back to all
    registered tools so routing never makes an existing capability unreachable.
    """

    available = set(all_tools if available_names is None else available_names)
    groups = matched_groups(user_message)
    if not groups:
        return [name for name in all_tools if name in available]
    selected = set().union(*(TOOL_GROUPS[group] for group in groups))
    selected.update(UNIVERSAL_TOOLS)
    selected &= available
    return [name for name in all_tools if name in selected]


def tool_specs_for_message(user_message: str) -> list[dict[str, object]]:
    names = set(tool_names_for_message(user_message))
    return [tool["spec"] for name, tool in all_tools.items() if name in names]
