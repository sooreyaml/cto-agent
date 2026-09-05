from fastapi import APIRouter

from src.health.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get(
    "/healthz",
    response_model=HealthResponse,
    summary="Liveness probe",
    description="Returns ok when the process is accepting HTTP traffic.",
)
async def healthz() -> dict[str, bool]:
    return {"ok": True}
