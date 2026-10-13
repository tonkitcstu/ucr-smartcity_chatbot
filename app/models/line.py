from typing import Literal

from pydantic import BaseModel


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


class QuickReplyButton(BaseModel):
    """ปุ่มใต้ข้อความหนึ่งปุ่มที่ตัวคุยเลือก · กดแล้วไลน์เปิดหน้าปักหมุด / กล้อง / อัลบั้มรูป"""
    type: Literal["location", "camera", "camera_roll"]
    label: str
