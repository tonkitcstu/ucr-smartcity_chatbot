"""การ์ด PDPA (ถ้อยคำตายตัว — TC7 ข้อยกเว้น 3) และการยอมรับ"""

import json
from pathlib import Path

from linebot.v3.messaging import FlexContainer, FlexMessage

from app.clients import database
from app.models.user import User

ACCEPT = "pdpa_accept"

_card = json.loads((Path(__file__).parent / "pdpa_card.json").read_text(encoding="utf-8"))


def card() -> FlexMessage:
    return FlexMessage(
        alt_text=_card["altText"],
        contents=FlexContainer.from_dict(_card["contents"]),
    )


async def accept(line_user_id: str) -> User:
    """สร้าง User ตอนกดยอมรับ · กดซ้ำได้ User เดิม เวลาเดิม"""
    return await database.insert_user(line_user_id)
