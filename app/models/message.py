from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class IncomingMessage(BaseModel):
    """ข้อความที่แกะจาก event แล้ว ยังไม่บันทึก · รูปไม่มี content"""
    line_event_id: str
    line_message_id: str
    reply_token: str
    type: Literal["text", "image"]
    content: str | None


class Message(IncomingMessage):
    """ข้อความที่บันทึกแล้ว"""
    message_id: UUID
    session_id: UUID


class TranscriptMessage(BaseModel):
    """ข้อความหนึ่งแถวของใบ อ่านจาก PSQL · รูปมี attachment · ตำแหน่งมี lat/lng"""
    message_id: UUID
    role: Literal["user", "assistant"]
    type: Literal["text", "image", "location"]
    content: str | None
    lat: float | None
    lng: float | None
    attachment_id: UUID | None
    file_path: str | None
