from uuid import UUID

from app.clients import database
from app.models.user import User


async def find_by_line_id(line_user_id: str) -> User | None:
    """ไม่เจอ = ยังไม่ยอมรับ PDPA"""
    return await database.select_user_by_line_id(line_user_id)


async def line_id_for(session_id: UUID) -> str:
    """LINE ID ของเจ้าของใบ — loading animation ต้องใช้ (ใบสั่งงานมีแค่ session_id)"""
    return await database.select_line_user_id(session_id)


async def mark_blocked(line_user_id: str) -> None:
    """ผู้แจ้งบล็อกบอท → ไม่ได้ข้อความทัก"""
    await database.mark_user_blocked(line_user_id)


async def mark_following(line_user_id: str) -> None:
    """ผู้แจ้งเพิ่มเพื่อนหรือเลิกบล็อก → ได้ข้อความทักอีก"""
    await database.mark_user_following(line_user_id)
