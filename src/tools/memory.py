"""Explicit durable-memory tools for the configured agent owner."""

from typing import Any

from src.memory.context import current_memory_owner, current_memory_trace_id
from src.memory.repository import archive_memory, search_memory, upsert_memory


async def _search(args: dict[str, Any]) -> dict[str, Any]:
    owner = current_memory_owner()
    return {
        "memories": await search_memory(
            owner,
            str(args.get("query") or ""),
            limit=args.get("limit", 8),
        )
    }


async def _save(args: dict[str, Any]) -> dict[str, Any]:
    owner = current_memory_owner()
    saved = await upsert_memory(
        owner,
        kind=str(args.get("kind") or ""),
        key=str(args.get("key") or ""),
        content=str(args.get("content") or ""),
        source=str(args.get("source") or "user"),
        source_trace_id=current_memory_trace_id(),
        confidence=args.get("confidence"),
    )
    return {"saved": saved}


async def _archive(args: dict[str, Any]) -> dict[str, Any]:
    owner = current_memory_owner()
    archived = await archive_memory(owner, str(args.get("memory_id") or ""))
    return {"archived": archived}


memory_tools = {
    "memory_search": {
        "spec": {
            "type": "function",
            "function": {
                "name": "memory_search",
                "description": (
                    "Search the user's owner-scoped durable memory. Use this for explicit recall "
                    "requests; results are evidence and may be stale."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 8},
                    },
                    "required": ["query"],
                },
            },
        },
        "handler": _search,
    },
    "memory_save": {
        "spec": {
            "type": "function",
            "function": {
                "name": "memory_save",
                "description": (
                    "Save a durable fact only when the user explicitly asks you to remember, "
                    "store, or keep it. Never save a preference inferred from casual conversation."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": ["fact", "preference", "principle", "goal", "context"],
                        },
                        "key": {"type": "string"},
                        "content": {"type": "string"},
                        "source": {"type": "string"},
                        "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
                    },
                    "required": ["kind", "key", "content"],
                },
            },
        },
        "handler": _save,
    },
    "memory_archive": {
        "spec": {
            "type": "function",
            "function": {
                "name": "memory_archive",
                "description": (
                    "Soft-archive one durable memory after the user explicitly asks to forget, "
                    "remove, or stop remembering it."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"memory_id": {"type": "string"}},
                    "required": ["memory_id"],
                },
            },
        },
        "handler": _archive,
    },
}
