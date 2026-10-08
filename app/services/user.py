from app.clients import database
from app.models.user import User


async def find_by_line_id(line_user_id: str) -> User | None:
    """ไม่เจอ = ยังไม่ยอมรับ PDPA"""
    return await database.select_user_by_line_id(line_user_id)
