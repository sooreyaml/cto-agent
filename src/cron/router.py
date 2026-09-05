from fastapi import APIRouter

from src.cron.dependencies import CronAuth
from src.cron.schemas import CronHealthResponse, DailyBriefResponse
from src.jobs.daily_brief import run_daily_brief
from src.slack.service import dispatch_detached

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
    description="Requires Authorization: Bearer $CRON_SECRET. Runs the brief job in the background.",
    responses={
        401: {"description": "Missing or invalid cron bearer token"},
        503: {"description": "CRON_SECRET is not configured"},
    },
)
async def daily_brief(_auth: CronAuth) -> dict[str, bool]:
    dispatch_detached("daily-brief", run_daily_brief)
    return {"ok": True, "dispatched": True}
