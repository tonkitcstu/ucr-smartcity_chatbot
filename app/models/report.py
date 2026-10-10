from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.attachment import AttachmentLink


class ReportDraft(BaseModel):
    """รายงานหนึ่งใบที่ AI ร่าง · location / images เป็นเลขป้าย [ตำแหน่ง n] / [รูป n]"""
    desc: str
    tags: list[str]
    location: int | None
    images: list[int]


class Analysis(BaseModel):
    """รูปแบบที่ตัววิเคราะห์ต้องตอบ (structured output)"""
    reports: list[ReportDraft]


class ReportRow(BaseModel):
    """รายงานหนึ่งแถว + รูปของมัน อ่านจาก PSQL"""
    report_id: UUID
    session_id: UUID
    user_id: UUID
    desc: str
    tags: list[str]
    lat: float | None
    lng: float | None
    attachment_ids: list[UUID]
    started_at: datetime
    created_at: datetime


class DashboardReport(BaseModel):
    """รายงานหนึ่งใบใน JSON ของแดชบอร์ด · ผู้แจ้งเป็น user_id ไม่ใช่ LINE ID (S8)"""
    report_id: UUID
    session_id: UUID
    user_id: UUID
    desc: str
    tags: list[str]
    lat: float | None
    lng: float | None
    attachments: list[AttachmentLink]
    started_at: datetime
    created_at: datetime
