"""สมองของ API แดชบอร์ด: แปลงของจาก PSQL เป็น JSON ที่ทีมออกแบบเห็น"""

from datetime import date, timedelta, timezone
from pathlib import Path
from uuid import UUID

from app.models.attachment import AttachmentLink
from app.models.message import DashboardMessage
from app.models.report import DashboardReport, ReportRow, Severity
from app.services import attachment, report, session

THAI_TIME = timezone(timedelta(hours=7))


async def list_reports(
    date: date | None,
    start_date: date | None,
    end_date: date | None,
    tag: str | None,
    severity: Severity | None,
    limit: int,
) -> list[DashboardReport]:
    rows = await report.find(date, start_date, end_date, tag, severity, limit)
    return [to_dashboard(row) for row in rows]


async def find_report(report_id: UUID) -> DashboardReport | None:
    """ไม่มีรายงานนี้ → None (api ตอบ 404)"""
    row = await report.find_one(report_id)
    return to_dashboard(row) if row else None


def to_dashboard(row: ReportRow) -> DashboardReport:
    """ช่องเดียวกับ PSQL · รูปเป็นลิงก์ · เวลาเป็นเวลาไทย"""
    return DashboardReport(
        report_id=row.report_id,
        session_id=row.session_id,
        user_id=row.user_id,
        desc=row.desc,
        tags=row.tags,
        severity=row.severity,
        affected_groups=row.affected_groups,
        time_periods=row.time_periods,
        place=row.place,
        lat=row.lat,
        lng=row.lng,
        attachments=[link(attachment_id) for attachment_id in row.attachment_ids],
        started_at=row.started_at.astimezone(THAI_TIME),
        created_at=row.created_at.astimezone(THAI_TIME),
    )


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
            status=message.status,
            attachment=link(message.attachment_id) if message.attachment_id else None,
        )
        for message in transcript
    ]


def link(attachment_id: UUID) -> AttachmentLink:
    return AttachmentLink(attachment_id=attachment_id, url=f"/api/dashboard/attachments/{attachment_id}")
