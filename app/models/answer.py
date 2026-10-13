from pydantic import BaseModel

from app.models.line import QuickReplyButton


class ChatAnswer(BaseModel):
    """คำตอบหนึ่งรอบของตัวคุย — รูปแบบที่ส่งให้ AI ตอบตาม
    texts = ข้อความที่ผู้แจ้งเห็น เรียงตามลำดับ ข้อความละกล่องในไลน์ · buttons ว่าง = ไม่ยื่นปุ่ม"""
    texts: list[str]
    buttons: list[QuickReplyButton]
