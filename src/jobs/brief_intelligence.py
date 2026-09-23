"""Deterministic signal extraction for the daily executive brief."""

from __future__ import annotations

import re
from typing import Any

from src.agent.context import bound_text, serialize_tool_result
from src.connections.redact import redact_obj, redact_secrets

MAX_SIGNALS = 12
MAX_BRIEF_CONTEXT_CHARS = 24_000
MAX_BRIEF_MESSAGE_CHARS = 1_900
_PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def _text(value: object, max_chars: int = 300) -> str:
    return redact_secrets(str(value or "").strip())[:max_chars]


def _url(value: object) -> str | None:
    text = _text(value, 500)
    return text if text.startswith(("https://", "http://")) else None


def _source_ok(part: object) -> tuple[bool, Any]:
    if not isinstance(part, dict) or not part.get("ok"):
        return False, None
    return True, part.get("data")


def extract_ci_signals(github_part: object) -> list[dict[str, Any]]:
    ok, data = _source_ok(github_part)
    if not ok or not isinstance(data, list):
        return []
    signals: list[dict[str, Any]] = []
    for repo in data:
        if not isinstance(repo, dict):
            continue
        for failure in repo.get("recent_failed_runs") or []:
            if not isinstance(failure, dict):
                continue
            severity = str(failure.get("severity") or "medium").lower()
            signal = (
                failure.get("failure_signal")
                if isinstance(failure.get("failure_signal"), dict)
                else {}
            )
            signals.append(
                {
                    "priority": "critical" if severity == "critical" else "high",
                    "action": f"Investigate failing {failure.get('repo') or repo.get('repo') or 'repository'} workflow",
                    "reason": signal.get("likely_cause")
                    or "A GitHub Actions workflow failed on a recently active repository.",
                    "source": "github",
                    "evidence_url": _url(failure.get("html_url") or failure.get("url")),
                    "confidence": "high" if failure.get("failed_jobs") else "medium",
                    "next_diagnostic": signal.get("next_diagnostic")
                    or "Open the failed job and inspect the first failing step.",
                }
            )
    return signals


def extract_work_signals(work_part: object) -> list[dict[str, Any]]:
    ok, data = _source_ok(work_part)
    if not ok or not isinstance(data, dict):
        return []
    signals: list[dict[str, Any]] = []
    for task in data.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        status = task.get("status")
        title = _text(task.get("title"), 200) or "Untitled task"
        if status == "blocked":
            signals.append(
                {
                    "priority": "high",
                    "action": f"Unblock task: {title}",
                    "reason": _text(task.get("blocked_reason"), 260)
                    or "The work board marks this task blocked.",
                    "source": "work",
                    "evidence_id": task.get("id"),
                    "confidence": "high",
                }
            )
        elif status == "open" and task.get("due_at"):
            signals.append(
                {
                    "priority": "medium",
                    "action": f"Review due task: {title}",
                    "reason": f"Open task due {str(task['due_at'])[:10]}.",
                    "source": "work",
                    "evidence_id": task.get("id"),
                    "confidence": "high",
                }
            )
    for commitment in data.get("commitments") or []:
        if not isinstance(commitment, dict) or not commitment.get("due_at"):
            continue
        signals.append(
            {
                "priority": "medium",
                "action": f"Review commitment: {_text(commitment.get('what'), 200)}",
                "reason": f"Open commitment due {str(commitment['due_at'])[:10]}.",
                "source": "work",
                "evidence_id": commitment.get("id"),
                "confidence": "high",
            }
        )
    return signals


def extract_calendar_signals(calendar_part: object) -> list[dict[str, Any]]:
    ok, data = _source_ok(calendar_part)
    if not ok or not isinstance(data, list):
        return []
    count = sum(
        len(item.get("events"))
        for item in data
        if isinstance(item, dict) and isinstance(item.get("events"), list)
    )
    if count == 0:
        return []
    return [
        {
            "priority": "low",
            "action": "Prepare for today's scheduled meetings",
            "reason": f"{count} calendar event(s) are scheduled today.",
            "source": "calendar",
            "evidence_id": "calendar:today",
            "confidence": "high",
        }
    ]


def extract_inbox_signals(gmail_part: object) -> list[dict[str, Any]]:
    ok, data = _source_ok(gmail_part)
    if not ok or not isinstance(data, list):
        return []
    signals: list[dict[str, Any]] = []
    for account in data:
        if not isinstance(account, dict):
            continue
        messages = account.get("messages") or []
        if not messages:
            continue
        subject = (
            _text((messages[0] or {}).get("subject"), 200) if isinstance(messages[0], dict) else ""
        )
        signals.append(
            {
                "priority": "medium",
                "action": "Triage unread inbox",
                "reason": f"{len(messages)} unread message(s); latest subject: {subject or 'not available'}.",
                "source": "gmail",
                "evidence_id": f"gmail:{account.get('account') or 'default'}:unread",
                "confidence": "medium",
            }
        )
    return signals


def rank_action_candidates(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for signal in sorted(
        signals,
        key=lambda item: (
            _PRIORITY_ORDER.get(str(item.get("priority")), 9),
            str(item.get("source") or ""),
            str(item.get("action") or ""),
        ),
    ):
        action = _text(signal.get("action"), 240)
        source = _text(signal.get("source"), 80)
        reason = _text(signal.get("reason"), 400)
        if not action or not source or not reason or action.lower() in seen:
            continue
        seen.add(action.lower())
        selected.append(
            {
                **signal,
                "action": action,
                "source": source,
                "reason": reason,
                "confidence": _text(signal.get("confidence"), 20) or "uncertain",
            }
        )
        if len(selected) >= MAX_SIGNALS:
            break
    return selected


def build_brief_signals(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    signals = [
        *extract_ci_signals(bundle.get("github")),
        *extract_work_signals(bundle.get("work")),
        *extract_calendar_signals(bundle.get("calendar")),
        *extract_inbox_signals(bundle.get("gmail")),
    ]
    return rank_action_candidates(signals)


def verify_action_candidate(action: dict[str, Any]) -> bool:
    action_text = str(action.get("action") or "").lower()
    if re.search(r"\b(?:completed|sent|merged|deleted)\b", action_text):
        return False
    return bool(
        action.get("source")
        and action.get("reason")
        and (
            action.get("evidence_url")
            or action.get("evidence_id")
            or action.get("confidence") == "uncertain"
        )
    )


def source_health(bundle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    health: dict[str, dict[str, Any]] = {}
    for name in ("work", "calendar", "gmail", "github", "granola"):
        part = bundle.get(name)
        if isinstance(part, dict):
            data = part.get("data")
            health[name] = {
                "ok": bool(part.get("ok")),
                "skipped": bool(isinstance(data, dict) and data.get("skipped")),
            }
        else:
            health[name] = {"ok": False, "skipped": False}
    return health


def evidence_urls(signals: list[dict[str, Any]]) -> list[str]:
    urls: list[str] = []
    for signal in signals:
        url = _text(signal.get("evidence_url"), 500)
        if url.startswith(("https://", "http://")) and url not in urls:
            urls.append(url)
        if len(urls) >= 20:
            break
    return urls


def prepare_brief_payload(bundle: dict[str, Any]) -> str:
    safe = redact_obj(bundle)
    encoded = serialize_tool_result(safe, max_chars=MAX_BRIEF_CONTEXT_CHARS)
    return encoded


def render_fallback_brief(
    bundle: dict[str, Any],
    signals: list[dict[str, Any]],
) -> str:
    lines = ["**Today**"]
    date = _text(bundle.get("date"), 40)
    if date:
        lines.append(f"- Brief generated {date[:10]}.")
    if signals:
        lines.append("\n**Top risks and next actions**")
        for signal in signals[:6]:
            line = f"- **{signal['priority'].title()}:** {signal['action']} — {signal['reason']}"
            url = _url(signal.get("evidence_url"))
            if url:
                line += f" [{signal.get('source', 'evidence')}]({url})"
            lines.append(line)
    else:
        lines.append("- No high-priority risks were identified from available sources.")
    for name, health in source_health(bundle).items():
        if not health["ok"] and not health["skipped"]:
            lines.append(f"- {name.title()} source unavailable; no action was inferred from it.")
    return bound_text("\n".join(lines), max_chars=MAX_BRIEF_MESSAGE_CHARS)


def brief_metadata(bundle: dict[str, Any], signals: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "source_health": source_health(bundle),
        "signal_count": len(signals),
        "action_count": sum(1 for signal in signals if verify_action_candidate(signal)),
        "evidence_urls": evidence_urls(signals),
    }
