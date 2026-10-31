from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.models.answer import ChatAnswer


# แถวของวันหนึ่งใน broadcasts
class Broadcast(BaseModel):
    broadcast_id: UUID
    forecast_date: date
    # เหตุที่ทัก ส่งให้ตัวคุยใช้แต่งข้อความ
    reason: str
    status: Literal["scheduled", "sent", "expired"]
    # ข้อความทักของวันนั้น ทุกคนได้ข้อความเดียวกัน · None = ยังไม่ได้แต่ง
    greeting: ChatAnswer | None = None
