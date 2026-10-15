from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.models.attachment import AttachmentLink
from app.models.line import IncomingMessage


class Message(IncomingMessage):
    """ข้อความที่บันทึกแล้ว"""
    message_id: UUID
    session_id: UUID


class TranscriptMessage(BaseModel):
    """ข้อความหนึ่งแถวของใบ อ่านจาก PSQL · รูปมี attachment · ตำแหน่งมี lat/lng"""
    message_id: UUID
    role: Literal["user", "assistant"]
    type: Literal["text", "image", "location", "sticker"]
    content: str | None
    lat: float | None
    lng: float | None
    status: Literal["pending", "answered", "skipped"]
    attachment_id: UUID | None
    file_path: str | None


class DashboardMessage(BaseModel):
    """ข้อความหนึ่งแถวใน JSON ของแดชบอร์ด · ไม่มี file_path"""
    message_id: UUID
    role: Literal["user", "assistant"]
    type: Literal["text", "image", "location", "sticker"]
    content: str | None
    lat: float | None
    lng: float | None
    attachment: AttachmentLink | None
