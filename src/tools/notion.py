from typing import Any

from src.config import get_settings
from src.exceptions import ConfigError
from src.integrations.notion import get_notion
from src.lib.notion_project_fields import (
    PROJECT_PROPS,
    extract_project_brief_fields,
    is_full_page,
    notion_status_clear_payload,
    notion_status_db_filter,
    notion_status_update_payload,
)
from src.lib.notion_task_fields import TASK_PROPS, map_task_row

P = {
    "projectTitle": PROJECT_PROPS["title"],
    "projectStatus": PROJECT_PROPS["status"],
    "projectDeadline": PROJECT_PROPS["deadline"],
    "projectPriority": PROJECT_PROPS["priority"],
    "projectCurrentFocus": PROJECT_PROPS["currentFocus"],
    "projectNextAction": PROJECT_PROPS["nextAction"],
    "taskTitle": TASK_PROPS["title"],
    "taskDue": TASK_PROPS["due"],
    "taskStatus": TASK_PROPS["status"],
    "taskProject": TASK_PROPS["project"],
}


def _require_projects_db() -> str:
    db_id = get_settings().NOTION_PROJECTS_DB_ID
    if not db_id:
        raise ConfigError("NOTION_PROJECTS_DB_ID not configured")
    return db_id


def _require_tasks_db() -> str:
    db_id = get_settings().NOTION_TASKS_DB_ID
    if not db_id:
        raise ConfigError("NOTION_TASKS_DB_ID not configured")
    return db_id


def _priority_payload(value: str) -> dict[str, Any]:
    stripped = value.strip()
    try:
        number = float(stripped)
    except ValueError:
        return {"select": {"name": value}}
    if stripped and str(int(number) if number.is_integer() else number) == stripped:
        return {"number": int(number) if number.is_integer() else number}
    return {"select": {"name": value}}


def _map_project_row(page: dict[str, Any]) -> dict[str, Any]:
    return {"id": page.get("id"), **extract_project_brief_fields(page), "url": page.get("url")}


def _map_pages(results: list[Any]) -> list[dict[str, Any]]:
    return [_map_project_row(r) for r in results if is_full_page(r)]


def _map_task_pages(results: list[Any]) -> list[dict[str, Any]]:
    return [map_task_row(r) for r in results if is_full_page(r)]


async def _search_projects(args: dict[str, Any]) -> list[dict[str, Any]]:
    db_id = _require_projects_db()
    notion = get_notion()
    status = args.get("status")
    filt = notion_status_db_filter(P["projectStatus"], status) if status else None
    res = await notion.databases.query(
        database_id=db_id,
        **({"filter": filt} if filt else {}),
        page_size=min(args.get("limit") or 20, 100),
    )
    return _map_pages(res.get("results") or [])


async def _create_project(args: dict[str, Any]) -> dict[str, Any]:
    db_id = _require_projects_db()
    notion = get_notion()
    props: dict[str, Any] = {
        P["projectTitle"]: {"title": [{"text": {"content": args["name"]}}]},
    }
    if args.get("status"):
        props[P["projectStatus"]] = notion_status_update_payload(args["status"])
    if args.get("deadline"):
        props[P["projectDeadline"]] = {"date": {"start": args["deadline"]}}
    if args.get("priority"):
        props[P["projectPriority"]] = _priority_payload(args["priority"])
    if args.get("current_focus"):
        props[P["projectCurrentFocus"]] = {
            "rich_text": [{"text": {"content": args["current_focus"]}}]
        }
    if args.get("next_action"):
        props[P["projectNextAction"]] = {"rich_text": [{"text": {"content": args["next_action"]}}]}
    created = await notion.pages.create(parent={"database_id": db_id}, properties=props)
    if not is_full_page(created):
        return {"id": created.get("id"), "url": created.get("url")}
    return _map_project_row(created)


async def _update_project(args: dict[str, Any]) -> dict[str, Any]:
    _require_projects_db()
    notion = get_notion()
    props: dict[str, Any] = {}
    if args.get("name") is not None:
        props[P["projectTitle"]] = {"title": [{"text": {"content": args["name"]}}]}
    if "status" in args:
        props[P["projectStatus"]] = (
            notion_status_clear_payload()
            if args["status"] == ""
            else notion_status_update_payload(args["status"])
        )
    if "deadline" in args:
        props[P["projectDeadline"]] = (
            {"date": {"start": args["deadline"]}} if args["deadline"] else {"date": None}
        )
    if "priority" in args:
        props[P["projectPriority"]] = (
            {"select": None} if args["priority"] == "" else _priority_payload(args["priority"])
        )
    if "current_focus" in args:
        props[P["projectCurrentFocus"]] = (
            {"rich_text": []}
            if args["current_focus"] == ""
            else {"rich_text": [{"text": {"content": args["current_focus"]}}]}
        )
    if "next_action" in args:
        props[P["projectNextAction"]] = (
            {"rich_text": []}
            if args["next_action"] == ""
            else {"rich_text": [{"text": {"content": args["next_action"]}}]}
        )
    updated = await notion.pages.update(page_id=args["page_id"], properties=props)
    if not is_full_page(updated):
        return {"id": updated.get("id"), "ok": True}
    return _map_project_row(updated)


async def _search_tasks(args: dict[str, Any]) -> list[dict[str, Any]]:
    db_id = _require_tasks_db()
    notion = get_notion()
    status = args.get("status")
    filt = notion_status_db_filter(P["taskStatus"], status) if status else None
    res = await notion.databases.query(
        database_id=db_id,
        **({"filter": filt} if filt else {}),
        page_size=min(args.get("limit") or 20, 100),
    )
    return _map_task_pages(res.get("results") or [])


async def _create_task(args: dict[str, Any]) -> dict[str, Any]:
    db_id = _require_tasks_db()
    notion = get_notion()
    props: dict[str, Any] = {
        P["taskTitle"]: {"title": [{"text": {"content": args["title"]}}]},
    }
    if args.get("due"):
        props[P["taskDue"]] = {"date": {"start": args["due"]}}
    if args.get("status"):
        props[P["taskStatus"]] = notion_status_update_payload(args["status"])
    if args.get("project_page_id"):
        props[P["taskProject"]] = {"relation": [{"id": args["project_page_id"]}]}
    created = await notion.pages.create(parent={"database_id": db_id}, properties=props)
    if not is_full_page(created):
        return {"id": created.get("id")}
    return map_task_row(created)


async def _update_task(args: dict[str, Any]) -> dict[str, Any]:
    _require_tasks_db()
    notion = get_notion()
    props: dict[str, Any] = {}
    if "title" in args:
        props[P["taskTitle"]] = {"title": [{"text": {"content": args["title"]}}]}
    if "due" in args:
        props[P["taskDue"]] = {"date": {"start": args["due"]}} if args["due"] else {"date": None}
    if "status" in args:
        props[P["taskStatus"]] = (
            notion_status_clear_payload()
            if args["status"] == ""
            else notion_status_update_payload(args["status"])
        )
    if "project_page_id" in args:
        props[P["taskProject"]] = {"relation": [{"id": args["project_page_id"]}]}
    updated = await notion.pages.update(page_id=args["page_id"], properties=props)
    if not is_full_page(updated):
        return {"id": updated.get("id"), "ok": True}
    return map_task_row(updated)


async def _describe_tasks_database(_args: dict[str, Any]) -> dict[str, Any]:
    db_id = _require_tasks_db()
    notion = get_notion()
    db = await notion.databases.retrieve(database_id=db_id)
    properties: dict[str, dict[str, Any]] = {}
    for name, prop in (db.get("properties") or {}).items():
        kind = prop.get("type")
        if kind == "select":
            properties[name] = {
                "type": "select",
                "options": [o.get("name") for o in (prop.get("select") or {}).get("options") or []],
            }
        elif kind == "status":
            properties[name] = {
                "type": "status",
                "options": [o.get("name") for o in (prop.get("status") or {}).get("options") or []],
            }
        elif kind == "relation":
            properties[name] = {
                "type": "relation",
                "database_id": (prop.get("relation") or {}).get("database_id"),
            }
        else:
            properties[name] = {"type": kind}
    return {"tasks_database_id": db_id, "properties": properties}


notion_tools = {
    "notion_search_projects": {
        "spec": {
            "type": "function",
            "function": {
                "name": "notion_search_projects",
                "description": (
                    "Search projects: returns name, status, priority, current focus, "
                    "next action, deadline, id. Optional status filter."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "description": "Optional status name to filter (exact)",
                        },
                        "limit": {"type": "integer", "description": "Max results (default 20)"},
                    },
                },
            },
        },
        "handler": _search_projects,
    },
    "notion_create_project": {
        "spec": {
            "type": "function",
            "function": {
                "name": "notion_create_project",
                "description": "Create a new project page in the Projects database.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Project title"},
                        "status": {
                            "type": "string",
                            "description": "Status option name (must exist in Notion)",
                        },
                        "deadline": {
                            "type": "string",
                            "description": "ISO date YYYY-MM-DD or empty",
                        },
                        "priority": {
                            "type": "string",
                            "description": "Select name or numeric string if Priority is a number",
                        },
                        "current_focus": {
                            "type": "string",
                            "description": "Current focus (rich text)",
                        },
                        "next_action": {"type": "string", "description": "Next action (rich text)"},
                    },
                    "required": ["name"],
                },
            },
        },
        "handler": _create_project,
    },
    "notion_update_project": {
        "spec": {
            "type": "function",
            "function": {
                "name": "notion_update_project",
                "description": "Update an existing project Notion page by page ID.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "page_id": {"type": "string", "description": "Notion page UUID"},
                        "name": {"type": "string"},
                        "status": {"type": "string"},
                        "deadline": {
                            "type": "string",
                            "description": "YYYY-MM-DD or empty to clear",
                        },
                        "priority": {"type": "string"},
                        "current_focus": {"type": "string"},
                        "next_action": {"type": "string"},
                    },
                    "required": ["page_id"],
                },
            },
        },
        "handler": _update_project,
    },
    "notion_search_tasks": {
        "spec": {
            "type": "function",
            "function": {
                "name": "notion_search_tasks",
                "description": (
                    "Search your Notion tasks database: name, status, due, optional project link. "
                    "Filter by status optionally."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "description": "Optional status filter"},
                        "limit": {"type": "integer"},
                    },
                },
            },
        },
        "handler": _search_tasks,
    },
    "notion_create_task": {
        "spec": {
            "type": "function",
            "function": {
                "name": "notion_create_task",
                "description": "Create a task in the Tasks database. Optionally link to a project page ID.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "due": {"type": "string", "description": "YYYY-MM-DD"},
                        "status": {"type": "string"},
                        "project_page_id": {
                            "type": "string",
                            "description": "Parent project Notion page UUID",
                        },
                    },
                    "required": ["title"],
                },
            },
        },
        "handler": _create_task,
    },
    "notion_update_task": {
        "spec": {
            "type": "function",
            "function": {
                "name": "notion_update_task",
                "description": "Update a task page by ID.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "page_id": {"type": "string"},
                        "title": {"type": "string"},
                        "due": {"type": "string"},
                        "status": {"type": "string"},
                        "project_page_id": {
                            "type": "string",
                            "description": "Set or replace project relation",
                        },
                    },
                    "required": ["page_id"],
                },
            },
        },
        "handler": _update_task,
    },
    "notion_describe_tasks_database": {
        "spec": {
            "type": "function",
            "function": {
                "name": "notion_describe_tasks_database",
                "description": (
                    "Return the tasks database schema: each property’s type and, for Status "
                    "(select or Notion status), every allowed option name. Use before create/update "
                    "when status values are unknown."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
        },
        "handler": _describe_tasks_database,
    },
}
