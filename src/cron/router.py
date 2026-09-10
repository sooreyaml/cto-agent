from fastapi import APIRouter

from src.cron.dependencies import CronAuth
from src.cron.schemas import CronDispatchResponse, CronHealthResponse
from src.cron.tasks import spawn_cron
from src.jobs.daily_brief import run_daily_brief
from src.jobs.due import run_due
from src.jobs.watch import run_watch

router = APIRouter(prefix="/cron", tags=["cron"])


@router.get(
    "/health",
    response_model=CronHealthResponse,
    summary="Cron route liveness",
)
async def cron_health() -> dict[str, str | bool]:
    return {"ok": True, "cron": "up"}


@router.post(
    "/daily-brief",
    response_model=CronDispatchResponse,
    summary="Dispatch the daily executive brief",
    description="Requires Authorization: Bearer $CRON_SECRET or X-Cron-Secret. Returns immediately; the brief runs in-process afterward.",
    responses={
        401: {"description": "Missing or invalid cron bearer token"},
        503: {"description": "CRON_SECRET is not configured"},
    },
)
async def daily_brief(_auth: CronAuth) -> dict[str, bool]:
    spawn_cron("daily-brief", run_daily_brief)
    return {"ok": True, "dispatched": True}


@router.post(
    "/due",
    response_model=CronDispatchResponse,
    summary="Send due reminders and commitment nudges",
    description="Requires Authorization: Bearer $CRON_SECRET or X-Cron-Secret. Returns immediately; DMs run in-process afterward.",
    responses={
        401: {"description": "Missing or invalid cron bearer token"},
        503: {"description": "CRON_SECRET is not configured"},
    },
)
async def due(_auth: CronAuth) -> dict[str, bool]:
    spawn_cron("due", run_due)
    return {"ok": True, "dispatched": True}


@router.post(
    "/watch",
    response_model=CronDispatchResponse,
    summary="Notify new GitHub Actions failures on active repos",
    description="Requires Authorization: Bearer $CRON_SECRET or X-Cron-Secret. Returns immediately; GitHub polling runs in-process afterward.",
    responses={
        401: {"description": "Missing or invalid cron bearer token"},
        503: {"description": "CRON_SECRET is not configured"},
    },
)
async def watch(_auth: CronAuth) -> dict[str, bool]:
    spawn_cron("watch", run_watch)
    return {"ok": True, "dispatched": True}
