from typing import Any
from urllib.parse import quote

from src.integrations.granola import granola_request


async def _list_meetings(args: dict[str, Any]) -> object:
    limit = min(args.get("limit") or 10, 50)
    return await granola_request(f"/meetings?limit={limit}")


async def _get_meeting(args: dict[str, Any]) -> object:
    return await granola_request(f"/meetings/{quote(args['meeting_id'], safe='')}")


async def _search(args: dict[str, Any]) -> object:
    limit = min(args.get("limit") or 10, 30)
    query = quote(args["query"])
    return await granola_request(f"/search?q={query}&limit={limit}")


granola_tools = {
    "granola_list_meetings": {
        "spec": {
            "type": "function",
            "function": {
                "name": "granola_list_meetings",
                "description": "List recent meetings/notes from Granola API (GET /meetings?limit=). Path may need customization.",
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
                "description": "Fetch a single Granola meeting/note by id (GET /meetings/:id).",
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
                "description": "Search Granola (GET /search?q=). Path may need customization for your workspace.",
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
