from uuid import UUID

from pydantic import BaseModel


class Attachment(BaseModel):
    """ไฟล์รูปที่เก็บแล้ว ผูกกับข้อความรูป"""
    attachment_id: UUID
    message_id: UUID
    file_path: str


class AttachmentLink(BaseModel):
    """ไฟล์แนบใน JSON ของแดชบอร์ด · url ชี้ไปเส้นดึงไฟล์"""
    attachment_id: UUID
    url: str
