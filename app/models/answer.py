from pydantic import BaseModel

from app.models.line import QuickReplyButton


class ChatAnswer(BaseModel):
    """คำตอบหนึ่งรอบของตัวคุย — รูปแบบที่ส่งให้ AI ตอบตาม · text = ข้อความที่ผู้แจ้งเห็น · buttons ว่าง = ไม่ยื่นปุ่ม"""
    text: str
    buttons: list[QuickReplyButton]
