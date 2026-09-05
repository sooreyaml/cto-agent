from collections.abc import Awaitable, Callable
from typing import Any

from src.config import get_settings
from src.tools.calendar import calendar_tools
from src.tools.github import github_tools
from src.tools.gmail import gmail_tools
from src.tools.google_connect import google_connect_tools
from src.tools.granola import granola_tools
from src.tools.notion import notion_tools
from src.tools.slack_reminders import slack_reminder_tools

ToolHandler = Callable[[Any], Awaitable[Any]]
ToolDef = dict[str, Any]

PROJECT_NOTION_TOOLS = {
    "notion_search_projects",
    "notion_create_project",
    "notion_update_project",
}
TASK_NOTION_TOOLS = {
    "notion_describe_tasks_database",
    "notion_search_tasks",
    "notion_create_task",
    "notion_update_task",
}


def _active_notion_tools() -> dict[str, ToolDef]:
    settings = get_settings()
    active: dict[str, ToolDef] = {}
    for name, tool in notion_tools.items():
        if name in PROJECT_NOTION_TOOLS and not settings.NOTION_PROJECTS_DB_ID:
            continue
        if name in TASK_NOTION_TOOLS and not settings.NOTION_TASKS_DB_ID:
            continue
        active[name] = tool
    return active


def _all_tools() -> dict[str, ToolDef]:
    return {
        **_active_notion_tools(),
        **slack_reminder_tools,
        **google_connect_tools,
        **gmail_tools,
        **calendar_tools,
        **github_tools,
        **granola_tools,
    }


all_tools = _all_tools()
tool_registry: dict[str, ToolHandler] = {name: tool["handler"] for name, tool in all_tools.items()}
tool_specs = [tool["spec"] for tool in all_tools.values()]
