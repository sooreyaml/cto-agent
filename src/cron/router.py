from fastapi import APIRouter

from src.cron.dependencies import CronAuth
from src.cron.schemas import CronHealthResponse, DailyBriefResponse, DueResponse, WatchResponse
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
    response_model=DailyBriefResponse,
    summary="Dispatch the daily executive brief",
    description="Requires Authorization: Bearer $CRON_SECRET. Runs the brief and DMs Discord before returning.",
    responses={
        401: {"description": "Missing or invalid cron bearer token"},
        503: {"description": "CRON_SECRET is not configured"},
    },
)
async def daily_brief(_auth: CronAuth) -> dict[str, bool]:
    await run_daily_brief()
    return {"ok": True, "dispatched": True}


@router.post(
    "/due",
    response_model=DueResponse,
    summary="Send due reminders and commitment nudges",
    description="Requires Authorization: Bearer $CRON_SECRET. DMs Discord before returning.",
    responses={
        401: {"description": "Missing or invalid cron bearer token"},
        503: {"description": "CRON_SECRET is not configured"},
    },
)
async def due(_auth: CronAuth) -> dict[str, bool | int]:
    counts = await run_due()
    return {"ok": True, **counts}


@router.post(
    "/watch",
    response_model=WatchResponse,
    summary="Notify new GitHub Actions failures on active repos",
    description="Requires Authorization: Bearer $CRON_SECRET. DMs Discord before returning.",
    responses={
        401: {"description": "Missing or invalid cron bearer token"},
        503: {"description": "CRON_SECRET is not configured"},
    },
)
async def watch(_auth: CronAuth) -> dict[str, bool | int]:
    counts = await run_watch()
    return {"ok": True, **counts}
