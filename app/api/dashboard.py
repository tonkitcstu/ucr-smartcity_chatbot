import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import FileResponse

from app.controllers import dashboard
from app.core import config
from app.models.message import DashboardMessage
from app.models.report import DashboardReport
from app.services import auth


def require_jwt(authorization: str | None = Header(default=None)) -> dict:
    """ด่านของทุกเส้น: ต้องมี Authorization: Bearer <jwt> ที่ทีมออกแบบออกให้"""
    if not config.SECRET_KEY:
        raise HTTPException(status_code=503, detail="SECRET_KEY is not set")
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Could not validate credentials")
    try:
        return auth.read_jwt(token.strip())
    except auth.Denied:
        raise HTTPException(status_code=401, detail="Could not validate credentials")


router = APIRouter(prefix="/api/dashboard", dependencies=[Depends(require_jwt)])


@router.get("/reports")
async def reports(
    date: datetime.date | None = None,
    tag: str | None = None,
    limit: int = Query(default=20, ge=1, le=200),
) -> list[DashboardReport]:
    return await dashboard.list_reports(date, tag, limit)


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
