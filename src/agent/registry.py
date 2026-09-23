from collections.abc import Awaitable, Callable
from typing import Any

from src.tools.calendar import calendar_tools
from src.tools.connections import connections_tools
from src.tools.github import github_tools
from src.tools.gmail import gmail_tools
from src.tools.google_connect import google_connect_tools
from src.tools.granola import granola_tools
from src.tools.memory import memory_tools
from src.tools.work import work_tools

ToolHandler = Callable[[Any], Awaitable[Any]]
ToolDef = dict[str, Any]


def _all_tools() -> dict[str, ToolDef]:
    tools: dict[str, ToolDef] = {
        **work_tools,
        **connections_tools,
        **google_connect_tools,
        **gmail_tools,
        **calendar_tools,
        **github_tools,
        **granola_tools,
        **memory_tools,
    }
    from src.config import get_settings

    if get_settings().slack_enabled:
        from src.tools.slack_reminders import slack_reminder_tools

        tools.update(slack_reminder_tools)
    return tools


all_tools = _all_tools()
tool_registry: dict[str, ToolHandler] = {name: tool["handler"] for name, tool in all_tools.items()}
tool_specs = [tool["spec"] for tool in all_tools.values()]
