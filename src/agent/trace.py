"""Metadata-only tracing for one agent turn.

Trace events deliberately exclude prompts, arguments, and tool payloads.  A
test sink can collect the events in-process; production callers get a stable
correlation id and structured log fields without copying user data into logs.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)
TraceSink = Callable[[dict[str, Any]], None]
_SENSITIVE_FIELDS = frozenset(
    {
        "arguments",
        "content",
        "messages",
        "payload",
        "prompt",
        "result",
        "tool_arguments",
        "tool_result",
    }
)


class AgentTrace:
    def __init__(self, *, trace_id: str | None = None, sink: TraceSink | None = None) -> None:
        self.trace_id = trace_id or uuid.uuid4().hex
        self._sink = sink
        self.events: list[dict[str, Any]] = []

    def emit(self, event: str, **fields: Any) -> None:
        payload: dict[str, Any] = {
            "event": event,
            "trace_id": self.trace_id,
            "at_ms": int(time.time() * 1000),
        }
        for key, value in fields.items():
            if key in _SENSITIVE_FIELDS:
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                payload[key] = value
            else:
                payload[key] = str(value)
        self.events.append(payload)
        logger.info(
            "agent trace event=%s trace_id=%s fields=%s",
            event,
            self.trace_id,
            {
                key: value
                for key, value in payload.items()
                if key not in {"event", "trace_id", "at_ms"}
            },
        )
        if self._sink is None:
            return
        try:
            self._sink(dict(payload))
        except Exception:
            logger.exception("agent trace sink failed trace_id=%s event=%s", self.trace_id, event)
