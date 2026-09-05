from typing import Any

TASK_PROPS = {
    "title": "Name",
    "due": "Due",
    "status": "Status",
    "project": "Project",
}


def title_from_page(page: dict[str, Any]) -> str:
    for prop in (page.get("properties") or {}).values():
        if isinstance(prop, dict) and prop.get("type") == "title":
            return "".join(t.get("plain_text", "") for t in prop.get("title") or []) or "Untitled"
    return "Untitled"


def map_task_row(page: dict[str, Any]) -> dict[str, Any]:
    props = page.get("properties") or {}
    status = ""
    st = props.get(TASK_PROPS["status"])
    if isinstance(st, dict):
        if st.get("type") == "status":
            status = (st.get("status") or {}).get("name") or ""
        elif st.get("type") == "select":
            status = (st.get("select") or {}).get("name") or ""
    due = None
    due_prop = props.get(TASK_PROPS["due"])
    if isinstance(due_prop, dict) and due_prop.get("type") == "date":
        due = (due_prop.get("date") or {}).get("start")
    project_page_id = None
    rel = props.get(TASK_PROPS["project"])
    if isinstance(rel, dict) and rel.get("type") == "relation" and rel.get("relation"):
        project_page_id = rel["relation"][0].get("id")
    return {
        "id": page.get("id"),
        "name": title_from_page(page),
        "status": status,
        "due": due,
        "projectPageId": project_page_id,
        "url": page.get("url"),
    }
