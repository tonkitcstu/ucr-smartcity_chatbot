"""state ของใบใน Redis (#245): ไม่มี key = IDLE, BUFFERING, PROCESSING, CLOSING
เปิดไฟล์นี้แล้วเห็นว่าเปลี่ยนจากอะไรไปเป็นอะไรได้บ้าง · คนเรียก (controller, worker, ตัวกวาด) ตัดสินว่าจะเปลี่ยนเมื่อไร"""

from uuid import UUID

from app.clients import redis
from app.models.session import Session


async def start_buffering(session: Session) -> bool:
    """IDLE → BUFFERING · True = เพิ่งเปลี่ยน (ผู้ชนะคนเดียว) · False = BUFFERING / PROCESSING อยู่แล้ว"""
    return await redis.set_buffering_if_idle(session.session_id)


async def start_processing(session_id: UUID) -> None:
    """BUFFERING → PROCESSING"""
    await redis.set_processing(session_id)


async def finish_processing(session_id: UUID) -> None:
    """PROCESSING → IDLE"""
    await redis.clear_state(session_id)


async def start_closing(session: Session) -> bool:
    """IDLE → CLOSING · True = ได้ใบนี้ไปปิด · False = กำลังคุย / มีคนปิดอยู่แล้ว"""
    return await redis.set_closing_if_idle(session.session_id)


async def stop_closing(session: Session) -> None:
    """CLOSING → IDLE"""
    await redis.clear_state(session.session_id)
