import json
import logging
from typing import Any

from src.agent.llm import MODEL, llm
from src.integrations.granola import granola_request
from src.work.repository import (
    brief_bundle,
    cancel_reminder,
    create_reminder,
    create_work,
    list_work,
    update_work,
)

logger = logging.getLogger(__name__)

_KIND_ENUM = ["priority", "task", "decision", "commitment"]


def _notes_to_text(payload: object) -> str:
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload
    return json.dumps(payload, default=str)


async def _list(args: dict[str, Any]) -> list[dict[str, Any]]:
    return await list_work(args)


async def _create(args: dict[str, Any]) -> dict[str, Any]:
    return await create_work(args)


async def _update(args: dict[str, Any]) -> dict[str, Any]:
    return await update_work(args)


async def _remind(args: dict[str, Any]) -> dict[str, Any]:
    action = str(args.get("action") or "create").strip()
    if action == "cancel":
        return await cancel_reminder(args)
    return await create_reminder(args)


async def _ingest_notes(args: dict[str, Any]) -> dict[str, Any]:
    text = str(args.get("text") or "").strip()
    meeting_id = str(args.get("granola_meeting_id") or "").strip()
    source = None
    if meeting_id:
        notes = _notes_to_text(await granola_request(f"/meetings/{meeting_id}"))
        source = f"granola:{meeting_id}"
    elif text:
        notes = text
        source = str(args.get("source") or "discord").strip() or "discord"
    else:
        raise ValueError("Provide text or granola_meeting_id")

    completion = await llm.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "Extract decisions and commitments from meeting notes. "
                    "Reply with JSON only: "
                    '{"decisions":[{"title":"","decision":"","rationale":""}],'
                    '"commitments":[{"who":"me","what":"","due_at":"YYYY-MM-DD or empty"}]} '
                    "Omit empty arrays. No markdown."
                ),
            },
            {"role": "user", "content": notes[:12000]},
        ],
        temperature=0.2,
        max_tokens=1024,
    )
    raw = (completion.choices[0].message.content or "").strip() if completion.choices else ""
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        parsed = json.loads(raw) if raw else {}
    except ValueError:
        logger.warning("work_ingest_notes: unparseable LLM output")
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}

    created: dict[str, list[dict[str, Any]]] = {"decisions": [], "commitments": []}
    for item in parsed.get("decisions") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        decision = str(item.get("decision") or "").strip()
        if not title or not decision:
            continue
        created["decisions"].append(
            await create_work(
                {
                    "kind": "decision",
                    "title": title,
                    "decision": decision,
                    "rationale": item.get("rationale") or None,
                }
            )
        )
    for item in parsed.get("commitments") or []:
        if not isinstance(item, dict):
            continue
        what = str(item.get("what") or "").strip()
        if not what:
            continue
        created["commitments"].append(
            await create_work(
                {
                    "kind": "commitment",
                    "who": item.get("who") or "me",
                    "what": what,
                    "due_at": item.get("due_at") or None,
                    "source": source,
                }
            )
        )
    return {"source": source, "created": created, "board": await brief_bundle()}


work_tools = {
    "work_list": {
        "spec": {
            "type": "function",
            "function": {
                "name": "work_list",
                "description": (
                    "List work items stored in Postgres: priorities, tasks, decisions, or commitments."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": _KIND_ENUM},
                        "status": {
                            "type": "string",
                            "description": "Filter by status when the kind has one",
                        },
                        "query": {"type": "string", "description": "Case-insensitive text search"},
                        "due_before": {
                            "type": "string",
                            "description": "ISO date or datetime; tasks and commitments only",
                        },
                        "limit": {"type": "integer"},
                    },
                    "required": ["kind"],
                },
            },
        },
        "handler": _list,
    },
    "work_create": {
        "spec": {
            "type": "function",
            "function": {
                "name": "work_create",
                "description": (
                    "Create a priority (max 5 open), task, decision, or commitment. "
                    "Priority: title, rank, status, notes. "
                    "Task: title, status, due_at, project, blocked_reason, notes, priority_id. "
                    "Decision: title, decision, rationale, decided_at, related_task_id. "
                    "Commitment: who, what, due_at, source, status, remind_at, related_task_id."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": _KIND_ENUM},
                        "title": {"type": "string"},
                        "rank": {"type": "integer"},
                        "status": {"type": "string"},
                        "notes": {"type": "string"},
                        "due_at": {"type": "string"},
                        "project": {"type": "string"},
                        "blocked_reason": {"type": "string"},
                        "priority_id": {"type": "string"},
                        "decision": {"type": "string"},
                        "rationale": {"type": "string"},
                        "decided_at": {"type": "string"},
                        "related_task_id": {"type": "string"},
                        "who": {"type": "string"},
                        "what": {"type": "string"},
                        "source": {"type": "string"},
                        "remind_at": {"type": "string"},
                    },
                    "required": ["kind"],
                },
            },
        },
        "handler": _create,
    },
    "work_update": {
        "spec": {
            "type": "function",
            "function": {
                "name": "work_update",
                "description": (
                    "Update a work item by kind and id. Pass an empty string to clear a nullable field."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": _KIND_ENUM},
                        "id": {"type": "string"},
                        "title": {"type": "string"},
                        "rank": {"type": "integer"},
                        "status": {"type": "string"},
                        "notes": {"type": "string"},
                        "due_at": {"type": "string"},
                        "project": {"type": "string"},
                        "blocked_reason": {"type": "string"},
                        "priority_id": {"type": "string"},
                        "decision": {"type": "string"},
                        "rationale": {"type": "string"},
                        "decided_at": {"type": "string"},
                        "related_task_id": {"type": "string"},
                        "who": {"type": "string"},
                        "what": {"type": "string"},
                        "source": {"type": "string"},
                        "remind_at": {"type": "string"},
                    },
                    "required": ["kind", "id"],
                },
            },
        },
        "handler": _update,
    },
    "work_remind": {
        "spec": {
            "type": "function",
            "function": {
                "name": "work_remind",
                "description": (
                    "Create or cancel an ad-hoc Discord reminder. "
                    "action=create needs message and fire_at (ISO). "
                    "action=cancel needs id. To nudge a commitment, prefer work_update remind_at."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["create", "cancel"]},
                        "message": {"type": "string"},
                        "fire_at": {"type": "string"},
                        "commitment_id": {"type": "string"},
                        "id": {"type": "string", "description": "Reminder id when cancelling"},
                    },
                },
            },
        },
        "handler": _remind,
    },
    "work_ingest_notes": {
        "spec": {
            "type": "function",
            "function": {
                "name": "work_ingest_notes",
                "description": (
                    "Extract decisions and commitments from pasted notes or a Granola meeting id "
                    "and write them to the work board."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "granola_meeting_id": {"type": "string"},
                        "source": {"type": "string"},
                    },
                },
            },
        },
        "handler": _ingest_notes,
    },
}
