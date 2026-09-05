from typing import Any

from src.config import get_settings

PROJECT_PROPS = {
    "title": "Name",
    "status": "Status",
    "deadline": "Deadline",
    "priority": "Priority",
    "currentFocus": "Current focus",
    "nextAction": "Next action",
}


def read_rich_text(prop: object) -> str:
    if not isinstance(prop, dict):
        return ""
    if prop.get("type") == "rich_text":
        return "".join(t.get("plain_text", "") for t in prop.get("rich_text") or [])
    if prop.get("type") == "title":
        return "".join(t.get("plain_text", "") for t in prop.get("title") or [])
    return ""


def read_priority(prop: object) -> str:
    if not isinstance(prop, dict):
        return ""
    kind = prop.get("type")
    if kind == "select":
        return (prop.get("select") or {}).get("name") or ""
    if kind == "status":
        return (prop.get("status") or {}).get("name") or ""
    if kind == "number" and prop.get("number") is not None:
        return str(prop["number"])
    if kind == "rich_text":
        return "".join(t.get("plain_text", "") for t in prop.get("rich_text") or [])
    return ""


def title_from_page(page: dict[str, Any], title_prop_name: str) -> str:
    props = page.get("properties") or {}
    named = props.get(title_prop_name)
    if isinstance(named, dict) and named.get("type") == "title":
        return "".join(t.get("plain_text", "") for t in named.get("title") or []) or "Untitled"
    for prop in props.values():
        if isinstance(prop, dict) and prop.get("type") == "title":
            return "".join(t.get("plain_text", "") for t in prop.get("title") or []) or "Untitled"
    return "Untitled"


def extract_project_brief_fields(page: dict[str, Any]) -> dict[str, Any]:
    props = page.get("properties") or {}
    status = ""
    st = props.get(PROJECT_PROPS["status"])
    if isinstance(st, dict):
        if st.get("type") == "status":
            status = (st.get("status") or {}).get("name") or ""
        elif st.get("type") == "select":
            status = (st.get("select") or {}).get("name") or ""
    deadline = None
    dl = props.get(PROJECT_PROPS["deadline"])
    if isinstance(dl, dict) and dl.get("type") == "date":
        deadline = (dl.get("date") or {}).get("start")
    return {
        "name": title_from_page(page, PROJECT_PROPS["title"]),
        "status": status,
        "priority": read_priority(props.get(PROJECT_PROPS["priority"])),
        "currentFocus": read_rich_text(props.get(PROJECT_PROPS["currentFocus"])),
        "nextAction": read_rich_text(props.get(PROJECT_PROPS["nextAction"])),
        "deadline": deadline,
    }


def notion_status_db_filter(property_name: str, equals: str) -> dict[str, Any]:
    if get_settings().NOTION_STATUS_PROPERTY_KIND == "select":
        return {"property": property_name, "select": {"equals": equals}}
    return {"property": property_name, "status": {"equals": equals}}


def notion_status_update_payload(name: str) -> dict[str, Any]:
    if get_settings().NOTION_STATUS_PROPERTY_KIND == "select":
        return {"select": {"name": name}}
    return {"status": {"name": name}}


def notion_status_clear_payload() -> dict[str, Any]:
    if get_settings().NOTION_STATUS_PROPERTY_KIND == "select":
        return {"select": None}
    return {"status": None}


def is_full_page(obj: object) -> bool:
    return isinstance(obj, dict) and obj.get("object") == "page" and "properties" in obj
