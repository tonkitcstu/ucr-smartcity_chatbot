from uuid import UUID

from pydantic import BaseModel


class Session(BaseModel):
    """ใบของการคุยหนึ่งเรื่อง — เปิดตอนข้อความแรก"""
    session_id: UUID
    user_id: UUID
