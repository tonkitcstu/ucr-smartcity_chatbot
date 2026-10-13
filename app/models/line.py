from typing import Literal

from pydantic import BaseModel


class QuickReplyButton(BaseModel):
    """ปุ่มใต้ข้อความหนึ่งปุ่มที่ตัวคุยเลือก · กดแล้วไลน์เปิดหน้าปักหมุด / กล้อง / อัลบั้มรูป"""
    type: Literal["location", "camera", "camera_roll"]
    label: str
