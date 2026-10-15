"""state ของใบใน Redis (#245): ไม่มี key = IDLE, BUFFERING, PROCESSING, CLOSING, SUSPENDED (#239)
เปิดไฟล์นี้แล้วเห็นว่าเปลี่ยนจากอะไรไปเป็นอะไรได้บ้าง · คนเรียก (controller, worker, ตัวกวาด) ตัดสินว่าจะเปลี่ยนเมื่อไร
ทุกการเปลี่ยนเช็คกับเขียนในคำสั่งเดียวของ Redis · ใบที่เป็น SUSPENDED ไม่มีใครเปลี่ยนได้ นอกจากหมดอายุเอง"""

from uuid import UUID

from app.clients import redis
from app.models.session import Session

SUSPEND_SECONDS = 24 * 60 * 60


async def start_buffering(session_id: UUID) -> bool:
    """IDLE → BUFFERING · True = เพิ่งเปลี่ยน (ผู้ชนะคนเดียว) · False = BUFFERING / PROCESSING อยู่แล้ว"""
    return await redis.set_buffering_if_idle(session_id)


async def start_processing(session_id: UUID) -> bool:
    """BUFFERING → PROCESSING · True = เปลี่ยนแล้ว · False = ไม่ได้เป็น BUFFERING (ใบถูกพักระหว่างรอเงียบ)"""
    return await redis.set_processing_if_buffering(session_id)


async def finish_processing(session_id: UUID) -> None:
    """PROCESSING → IDLE · ใบถูกพักระหว่าง AI กำลังตอบ → ยังเป็น SUSPENDED"""
    await redis.clear_state_if_processing(session_id)


async def start_closing(session: Session) -> bool:
    """IDLE → CLOSING · True = ได้ใบนี้ไปปิด · False = กำลังคุย / มีคนปิดอยู่แล้ว / ถูกพัก"""
    return await redis.set_closing_if_idle(session.session_id)


async def stop_closing(session: Session) -> None:
    """CLOSING → IDLE · ใบถูกพักระหว่างปิด → ยังเป็น SUSPENDED"""
    await redis.clear_state_if_closing(session.session_id)


async def is_suspended(session_id: UUID) -> bool:
    return await redis.get_state(session_id) == "SUSPENDED"


async def suspend(session: Session) -> None:
    """state ไหนก็ได้ → SUSPENDED · หมดอายุเองใน 24 ชั่วโมงแล้วใบเป็น IDLE"""
    await redis.set_suspended(session.session_id, SUSPEND_SECONDS)
