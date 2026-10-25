import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import FileResponse

from app.controllers import dashboard
from app.core import config
from app.models.message import DashboardMessage
from app.models.report import DashboardReport, Severity
from app.services import auth


def require_api_key(authorization: str | None = Header(default=None)) -> None:
    """ด่านของทุกเส้น: ต้องมี Authorization: Bearer <กุญแจ> ที่ตรงกับ DASHBOARD_API_KEY ใน .env"""
    if not config.DASHBOARD_API_KEY:
        raise HTTPException(status_code=503, detail="DASHBOARD_API_KEY is not set")
    scheme, _, key = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not auth.is_valid_key(key.strip()):
        raise HTTPException(status_code=401, detail="Invalid API key")


router = APIRouter(prefix="/api/dashboard", dependencies=[Depends(require_api_key)])


@router.get("/reports")
async def reports(
    date: datetime.date | None = None,
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
    tag: str | None = None,
    severity: Severity | None = None,
    limit: int = Query(default=20, ge=1, le=200),
) -> list[DashboardReport]:
    return await dashboard.list_reports(date, start_date, end_date, tag, severity, limit)


@router.get("/reports/{report_id}")
async def one_report(report_id: UUID) -> DashboardReport:
    found = await dashboard.find_report(report_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return found


@router.get("/attachments/{attachment_id}")
async def attachment(attachment_id: UUID) -> FileResponse:
    path = await dashboard.find_attachment(attachment_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/transcripts/{session_id}")
async def transcript(session_id: UUID) -> list[DashboardMessage]:
    messages = await dashboard.read_transcript(session_id)
    if not messages:
        raise HTTPException(status_code=404, detail="Transcript not found")
    return messages
