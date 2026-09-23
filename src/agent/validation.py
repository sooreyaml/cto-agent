"""Provider-neutral validation for model-generated tool arguments."""

from __future__ import annotations

import json
from typing import Any


def parse_tool_arguments(spec: dict[str, Any], raw_arguments: str | None) -> dict[str, Any]:
    """Decode an object and reject missing or unknown top-level fields.

    Handler-specific validation still owns enums, dates, and cross-field rules.
    This guard catches malformed provider output before it reaches side effects.
    """

    if raw_arguments is not None and not isinstance(raw_arguments, str):
        raise ValueError("tool arguments must be a JSON string")
    try:
        parsed = json.loads(raw_arguments or "{}")
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("tool arguments are not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("tool arguments must be a JSON object")

    function = spec.get("function") if isinstance(spec, dict) else None
    parameters = function.get("parameters") if isinstance(function, dict) else None
    if not isinstance(parameters, dict):
        return parsed
    properties = parameters.get("properties")
    if not isinstance(properties, dict):
        properties = {}
    required = parameters.get("required")
    required_names = (
        {str(name) for name in required if isinstance(name, str)}
        if isinstance(required, list)
        else set()
    )
    missing = sorted(name for name in required_names if name not in parsed)
    if missing:
        raise ValueError(f"missing required tool argument(s): {', '.join(missing)}")
    unknown = sorted(name for name in parsed if name not in properties)
    if unknown:
        raise ValueError(f"unknown tool argument(s): {', '.join(unknown)}")
    return parsed
