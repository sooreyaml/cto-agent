"""Context and tool-result budgets used by the agent loop."""

from __future__ import annotations

import json
from typing import Any

from src.memory.repository import sanitize_tool_history

MAX_HISTORY_MESSAGES = 24
MAX_HISTORY_CHARS = 24_000
MAX_WORK_CONTEXT_CHARS = 8_000
MAX_TOOL_RESULT_CHARS = 12_000


def _message_size(message: dict[str, Any]) -> int:
    return len(json.dumps(message, default=str, ensure_ascii=False))


def bound_history(
    history: list[dict[str, Any]],
    *,
    max_messages: int = MAX_HISTORY_MESSAGES,
    max_chars: int = MAX_HISTORY_CHARS,
) -> list[dict[str, Any]]:
    """Keep the newest complete tool-call history within both budgets."""

    selected: list[dict[str, Any]] = []
    chars = 0
    for message in reversed(history[-max_messages:]):
        size = _message_size(message)
        if size > max_chars:
            continue
        if selected and chars + size > max_chars:
            break
        selected.append(message)
        chars += size
    selected.reverse()
    return sanitize_tool_history(selected)


def bound_text(text: str, *, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    marker = "\n[context truncated]"
    if max_chars <= len(marker):
        return marker[-max_chars:]
    return text[: max_chars - len(marker)].rstrip() + marker


def serialize_tool_result(result: Any, *, max_chars: int = MAX_TOOL_RESULT_CHARS) -> str:
    """Serialize tool data without allowing one integration to consume the context."""

    serialized = json.dumps(result, default=str, ensure_ascii=False)
    if len(serialized) <= max_chars:
        return serialized
    message = "Tool output exceeded the context budget; request a narrower result."
    marker = {"truncated": True, "preview": "", "message": message}
    encoded_marker = json.dumps(marker, ensure_ascii=False)
    if len(encoded_marker) >= max_chars:
        return encoded_marker

    low, high = 0, len(serialized)
    best = encoded_marker
    while low <= high:
        middle = (low + high) // 2
        marker["preview"] = serialized[:middle].rstrip()
        candidate = json.dumps(marker, ensure_ascii=False)
        if len(candidate) <= max_chars:
            best = candidate
            low = middle + 1
        else:
            high = middle - 1
    return best
