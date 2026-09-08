from collections.abc import Awaitable, Callable
from typing import Any

from src.tools.calendar import calendar_tools
from src.tools.connections import connections_tools
from src.tools.github import github_tools
from src.tools.gmail import gmail_tools
from src.tools.google_connect import google_connect_tools
from src.tools.granola import granola_tools
from src.tools.work import work_tools

ToolHandler = Callable[[Any], Awaitable[Any]]
ToolDef = dict[str, Any]


def _all_tools() -> dict[str, ToolDef]:
    return {
        **work_tools,
        **connections_tools,
        **google_connect_tools,
        **gmail_tools,
        **calendar_tools,
        **github_tools,
        **granola_tools,
    }


all_tools = _all_tools()
tool_registry: dict[str, ToolHandler] = {name: tool["handler"] for name, tool in all_tools.items()}
tool_specs = [tool["spec"] for tool in all_tools.values()]
