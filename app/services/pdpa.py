"""การ์ด PDPA (ถ้อยคำตายตัว — TC7 ข้อยกเว้น 3) และการยอมรับ"""

import json
from pathlib import Path

from linebot.v3.messaging import FlexContainer, FlexMessage, TextMessage

from app.clients import database
from app.models.user import User

ACCEPT = "pdpa_accept"

# ถ้อยคำตายตัวหลังกดยอมรับ — Idea ตัดสิน 2026-10-23 นับรวมกับการ์ด PDPA (TC7 ข้อยกเว้น 3)
# บอกว่าเริ่มคุยได้ด้วยการพิมพ์เล่า พร้อมตัวอย่างหนึ่งเรื่อง
WELCOME_TEXT = (
    "ขอบคุณที่ยอมรับค่ะ เริ่มคุยกับเมืองได้เลยด้วยการพิมพ์เล่าเรื่องแถวบ้าน "
    "เช่น วันนี้หน้าบ้านมีน้ำท่วมขังหลังฝนตก"
)

_card = json.loads((Path(__file__).parent / "pdpa_card.json").read_text(encoding="utf-8"))


def card() -> FlexMessage:
    return FlexMessage(
        alt_text=_card["altText"],
        contents=FlexContainer.from_dict(_card["contents"]),
    )


def welcome_message() -> TextMessage:
    return TextMessage(text=WELCOME_TEXT)


async def accept(line_user_id: str) -> User:
    """สร้าง User ตอนกดยอมรับ · กดซ้ำได้ User เดิม เวลาเดิม"""
    return await database.insert_user(line_user_id)
