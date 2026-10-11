from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.models.attachment import AttachmentLink


class IncomingMessage(BaseModel):
    """ข้อความที่แกะจาก event แล้ว ยังไม่บันทึก · รูปและตำแหน่งไม่มี content · ตำแหน่งมี lat/lng
    สติกเกอร์ content = keywords ที่ LINE ใช้บรรยาย"""
    line_event_id: str
    line_message_id: str
    reply_token: str
    type: Literal["text", "image", "location", "sticker"]
    content: str | None
    lat: float | None = None
    lng: float | None = None


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
