from typing import Any

from src.integrations.granola import granola_get_meeting, granola_list_meetings, granola_search


async def _list_meetings(args: dict[str, Any]) -> object:
    return await granola_list_meetings(min(args.get("limit") or 10, 50))


async def _get_meeting(args: dict[str, Any]) -> object:
    return await granola_get_meeting(str(args["meeting_id"]))


async def _search(args: dict[str, Any]) -> object:
    return await granola_search(str(args["query"]), min(args.get("limit") or 10, 30))


granola_tools = {
    "granola_list_meetings": {
        "spec": {
            "type": "function",
            "function": {
                "name": "granola_list_meetings",
                "description": (
                    "List recent Granola meetings. If not connected, tell the user to say "
                    "“connect granola” and send the sign-in link from connections_connect."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"limit": {"type": "integer"}},
                },
            },
        },
        "handler": _list_meetings,
    },
    "granola_get_meeting": {
        "spec": {
            "type": "function",
            "function": {
                "name": "granola_get_meeting",
                "description": "Fetch a Granola meeting/note by id after connect granola.",
                "parameters": {
                    "type": "object",
                    "properties": {"meeting_id": {"type": "string"}},
                    "required": ["meeting_id"],
                },
            },
        },
        "handler": _get_meeting,
    },
    "granola_search": {
        "spec": {
            "type": "function",
            "function": {
                "name": "granola_search",
                "description": "Search Granola meeting notes (MCP query after connect granola).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["query"],
                },
            },
        },
        "handler": _search,
    },
}
