from pydantic import BaseModel


class CronHealthResponse(BaseModel):
    ok: bool
    cron: str


class DailyBriefResponse(BaseModel):
    ok: bool
    dispatched: bool


class DueResponse(BaseModel):
    ok: bool
    reminders: int
    commitments: int


class WatchResponse(BaseModel):
    ok: bool
    failures: int
    notified: int
