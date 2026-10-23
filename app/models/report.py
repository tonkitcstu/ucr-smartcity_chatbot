from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.models.attachment import AttachmentLink

# ความรุนแรงของเรื่อง · ความหมายของแต่ละระดับเขียนไว้ใน ANALYSER_PROMPT (app/core/default_config.py)
Severity = Literal["low", "medium", "high"]

# ใครได้รับผลกระทบ · AI เลือกได้เฉพาะค่าในนี้ แดชบอร์ดจึงนับรวมข้ามรายงานได้
AffectedGroup = Literal["elderly", "children", "disabled", "pedestrians", "drivers", "workers", "residents"]

# ช่วงเวลาที่คนใช้ที่ตรงนั้นและเจอปัญหาจริง · ช่วงชั่วโมงเขียนไว้ใน ANALYSER_PROMPT ให้เทียบกับข้อมูล sensor ได้
TimePeriod = Literal["morning", "midday", "evening", "night"]


# รายงานหนึ่งใบที่ AI ร่าง · location / images เป็นเลขป้าย [ตำแหน่ง n] / [รูป n]
class ReportDraft(BaseModel):
    desc: str
    tags: list[str]
    severity: Severity
    affected_groups: list[AffectedGroup]
    time_periods: list[TimePeriod]
    place: str | None
    location: int | None
    images: list[int]


# รูปแบบที่ตัววิเคราะห์ต้องตอบ (structured output)
class Analysis(BaseModel):
    reports: list[ReportDraft]


# รายงานหนึ่งแถว + รูปของมัน อ่านจาก PSQL
class ReportRow(BaseModel):
    report_id: UUID
    session_id: UUID
    user_id: UUID
    desc: str
    tags: list[str]
    severity: Severity
    affected_groups: list[AffectedGroup]
    time_periods: list[TimePeriod]
    place: str | None
    lat: float | None
    lng: float | None
    attachment_ids: list[UUID]
    started_at: datetime
    created_at: datetime


# รายงานหนึ่งใบใน JSON ของแดชบอร์ด · ผู้แจ้งเป็น user_id ไม่ใช่ LINE ID (S8)
class DashboardReport(BaseModel):
    report_id: UUID
    session_id: UUID
    user_id: UUID
    desc: str
    tags: list[str]
    severity: Severity
    affected_groups: list[AffectedGroup]
    time_periods: list[TimePeriod]
    place: str | None
    lat: float | None
    lng: float | None
    attachments: list[AttachmentLink]
    started_at: datetime
    created_at: datetime
