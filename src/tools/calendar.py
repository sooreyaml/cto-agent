from typing import Any

from fastapi.concurrency import run_in_threadpool

from src.config import get_settings
from src.integrations.google import get_calendar

PRIMARY = "primary"


def _tz() -> str:
    return get_settings().TIMEZONE or "UTC"


def _list_sync(time_min: str, time_max: str, max_results: int) -> list[dict[str, Any]]:
    cal = get_calendar()
    res = (
        cal.events()
        .list(
            calendarId=PRIMARY,
            timeMin=time_min,
            timeMax=time_max,
            timeZone=_tz(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=max_results,
        )
        .execute()
    )
    return [
        {
            "id": event.get("id"),
            "summary": event.get("summary"),
            "start": (event.get("start") or {}).get("dateTime")
            or (event.get("start") or {}).get("date"),
            "end": (event.get("end") or {}).get("dateTime") or (event.get("end") or {}).get("date"),
            "htmlLink": event.get("htmlLink"),
            "status": event.get("status"),
        }
        for event in res.get("items") or []
    ]


def _get_sync(event_id: str) -> dict[str, Any]:
    cal = get_calendar()
    event = cal.events().get(calendarId=PRIMARY, eventId=event_id).execute()
    return {
        "id": event.get("id"),
        "summary": event.get("summary"),
        "description": event.get("description"),
        "start": (event.get("start") or {}).get("dateTime")
        or (event.get("start") or {}).get("date"),
        "end": (event.get("end") or {}).get("dateTime") or (event.get("end") or {}).get("date"),
        "htmlLink": event.get("htmlLink"),
        "attendees": [
            {"email": a.get("email"), "responseStatus": a.get("responseStatus")}
            for a in event.get("attendees") or []
        ],
    }


def _create_sync(
    summary: str, start_iso: str, end_iso: str, description: str | None
) -> dict[str, Any]:
    cal = get_calendar()
    created = (
        cal.events()
        .insert(
            calendarId=PRIMARY,
            body={
                "summary": summary,
                "description": description,
                "start": {"dateTime": start_iso, "timeZone": _tz()},
                "end": {"dateTime": end_iso, "timeZone": _tz()},
            },
        )
        .execute()
    )
    return {
        "id": created.get("id"),
        "htmlLink": created.get("htmlLink"),
        "start": (created.get("start") or {}).get("dateTime"),
        "end": (created.get("end") or {}).get("dateTime"),
    }


def _update_sync(args: dict[str, Any]) -> dict[str, Any]:
    cal = get_calendar()
    body = cal.events().get(calendarId=PRIMARY, eventId=args["event_id"]).execute()
    if "summary" in args:
        body["summary"] = args["summary"]
    if "description" in args:
        body["description"] = args["description"]
    if "start_iso" in args:
        start = dict(body.get("start") or {})
        start["dateTime"] = args["start_iso"]
        start["timeZone"] = _tz()
        body["start"] = start
    if "end_iso" in args:
        end = dict(body.get("end") or {})
        end["dateTime"] = args["end_iso"]
        end["timeZone"] = _tz()
        body["end"] = end
    updated = cal.events().update(calendarId=PRIMARY, eventId=args["event_id"], body=body).execute()
    return {
        "id": updated.get("id"),
        "htmlLink": updated.get("htmlLink"),
        "start": (updated.get("start") or {}).get("dateTime"),
        "end": (updated.get("end") or {}).get("dateTime"),
    }


def _delete_sync(event_id: str) -> dict[str, Any]:
    cal = get_calendar()
    cal.events().delete(calendarId=PRIMARY, eventId=event_id).execute()
    return {"deleted": True, "event_id": event_id}


async def _list_events(args: dict[str, Any]) -> list[dict[str, Any]]:
    return await run_in_threadpool(
        _list_sync,
        args["time_min"],
        args["time_max"],
        min(args.get("max_results") or 50, 250),
    )


async def _get_event(args: dict[str, Any]) -> dict[str, Any]:
    return await run_in_threadpool(_get_sync, args["event_id"])


async def _create_event(args: dict[str, Any]) -> dict[str, Any]:
    return await run_in_threadpool(
        _create_sync,
        args["summary"],
        args["start_iso"],
        args["end_iso"],
        args.get("description"),
    )


async def _update_event(args: dict[str, Any]) -> dict[str, Any]:
    return await run_in_threadpool(_update_sync, args)


async def _delete_event(args: dict[str, Any]) -> dict[str, Any]:
    return await run_in_threadpool(_delete_sync, args["event_id"])


calendar_tools = {
    "calendar_list_events": {
        "spec": {
            "type": "function",
            "function": {
                "name": "calendar_list_events",
                "description": "List Google Calendar events in a time window (ISO timeMin/timeMax).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "time_min": {"type": "string", "description": "ISO 8601 start"},
                        "time_max": {"type": "string", "description": "ISO 8601 end"},
                        "max_results": {"type": "integer"},
                    },
                    "required": ["time_min", "time_max"],
                },
            },
        },
        "handler": _list_events,
    },
    "calendar_get_event": {
        "spec": {
            "type": "function",
            "function": {
                "name": "calendar_get_event",
                "description": "Get one calendar event by id.",
                "parameters": {
                    "type": "object",
                    "properties": {"event_id": {"type": "string"}},
                    "required": ["event_id"],
                },
            },
        },
        "handler": _get_event,
    },
    "calendar_create_event": {
        "spec": {
            "type": "function",
            "function": {
                "name": "calendar_create_event",
                "description": "Create a calendar event. Use ISO datetimes for timed events.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string"},
                        "start_iso": {"type": "string", "description": "ISO start datetime"},
                        "end_iso": {"type": "string", "description": "ISO end datetime"},
                        "description": {"type": "string"},
                    },
                    "required": ["summary", "start_iso", "end_iso"],
                },
            },
        },
        "handler": _create_event,
    },
    "calendar_update_event": {
        "spec": {
            "type": "function",
            "function": {
                "name": "calendar_update_event",
                "description": "Patch an existing event (partial). Omit fields you do not change.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "event_id": {"type": "string"},
                        "summary": {"type": "string"},
                        "start_iso": {"type": "string"},
                        "end_iso": {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["event_id"],
                },
            },
        },
        "handler": _update_event,
    },
    "calendar_delete_event": {
        "spec": {
            "type": "function",
            "function": {
                "name": "calendar_delete_event",
                "description": "Delete a calendar event permanently.",
                "parameters": {
                    "type": "object",
                    "properties": {"event_id": {"type": "string"}},
                    "required": ["event_id"],
                },
            },
        },
        "handler": _delete_event,
    },
}
