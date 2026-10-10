"""สมองของ API แดชบอร์ด: แปลงของจาก PSQL เป็น JSON ที่ทีมออกแบบเห็น"""

from datetime import date, timedelta, timezone
from pathlib import Path
from uuid import UUID

from app.models.attachment import AttachmentLink
from app.models.message import DashboardMessage
from app.models.report import DashboardReport
from app.services import attachment, report, session

THAI_TIME = timezone(timedelta(hours=7))


async def list_reports(date: date | None, tag: str | None, limit: int) -> list[DashboardReport]:
    """ช่องเดียวกับ PSQL · รูปเป็นลิงก์ · เวลาเป็นเวลาไทย"""
    rows = await report.find(date, tag, limit)
    return [
        DashboardReport(
            report_id=row.report_id,
            session_id=row.session_id,
            user_id=row.user_id,
            desc=row.desc,
            tags=row.tags,
            lat=row.lat,
            lng=row.lng,
            attachments=[link(attachment_id) for attachment_id in row.attachment_ids],
            started_at=row.started_at.astimezone(THAI_TIME),
            created_at=row.created_at.astimezone(THAI_TIME),
        )
        for row in rows
    ]


async def find_attachment(attachment_id: UUID) -> Path | None:
    return await attachment.find_file(attachment_id)


async def read_transcript(session_id: UUID) -> list[DashboardMessage]:
    """ข้อความทั้งใบ เรียงตามเวลา · แถวรูปได้ลิงก์ ไม่ส่ง file_path"""
    transcript = await session.read_transcript(session_id)
    return [
        DashboardMessage(
            message_id=message.message_id,
            role=message.role,
            type=message.type,
            content=message.content,
            lat=message.lat,
            lng=message.lng,
            attachment=link(message.attachment_id) if message.attachment_id else None,
        )
        for message in transcript
    ]


def link(attachment_id: UUID) -> AttachmentLink:
    return AttachmentLink(attachment_id=attachment_id, url=f"/api/dashboard/attachments/{attachment_id}")
