from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class IncomingMessage(BaseModel):
    """ข้อความที่แกะจาก event แล้ว ยังไม่บันทึก"""
    line_event_id: str
    line_message_id: str
    reply_token: str
    type: Literal["text"]
    content: str


class Message(IncomingMessage):
    """ข้อความที่บันทึกแล้ว"""
    message_id: UUID
    session_id: UUID
