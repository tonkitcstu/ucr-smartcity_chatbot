from uuid import UUID

from pydantic import BaseModel


class Attachment(BaseModel):
    """ไฟล์รูปที่เก็บแล้ว ผูกกับข้อความรูป"""
    attachment_id: UUID
    message_id: UUID
    file_path: str
