from fastapi import APIRouter, Request, Response

from app.controllers import health
from app.models.health import HealthStatus

router = APIRouter()


@router.get("/health")
async def read_health(request: Request, response: Response) -> HealthStatus:
    """อยู่ครบ → 200 · ขาดตัวใดตัวหนึ่ง → 503 · JSON หน้าตาเดียวกันทั้งสองกรณี"""
    status = await health.check(request.app.state.background)
    if not all(status.model_dump().values()):
        response.status_code = 503
    return status
