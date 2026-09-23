"""Code-enforced guardrails for irreversible tool calls."""

from __future__ import annotations

import re

HIGH_RISK_TOOLS = frozenset(
    {
        "gmail_send_message",
        "calendar_delete_event",
        "github_merge_pull_request",
        "connections_delete",
        "slack_cancel_reminder",
    }
)
_EXPLICIT_CONFIRMATION = re.compile(
    r"\b(?:confirm|confirmed|approve|approved|go ahead|proceed|send it|merge it|delete it|cancel it)\b",
    re.IGNORECASE,
)


def requires_explicit_confirmation(tool_name: str) -> bool:
    return tool_name in HIGH_RISK_TOOLS


def has_explicit_confirmation(user_message: str, tool_name: str) -> bool:
    """Require a confirmation phrase in the current turn for high-risk tools.

    A bare "yes" is intentionally not accepted: the model must ask the user
    to confirm the exact action in a fresh turn, preventing stale approvals.
    """

    if not requires_explicit_confirmation(tool_name):
        return True
    return bool(_EXPLICIT_CONFIRMATION.search(user_message or ""))
