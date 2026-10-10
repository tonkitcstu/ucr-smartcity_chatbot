"""ใบของการคุย: หา/สร้างใบ, บันทึกข้อความ, buffer, state, ประวัติที่คุยมา, ปิดใบ"""

import time
from uuid import UUID

from app.clients import database, redis
from app.core.config import CLOSE_AFTER_MINUTES
from app.models.context import ContextMessage
from app.models.message import IncomingMessage, Message
from app.models.session import Session
from app.models.user import User


async def open_for(user: User) -> Session:
    """หาใบที่เปิดอยู่ ไม่มีก็สร้าง"""
    return await database.open_session(user.user_id)


async def save_message(session: Session, incoming: IncomingMessage) -> Message:
    """บันทึกเป็น user (ผู้แจ้ง) · ยังไม่ตอบ"""
    return await database.insert_message(session.session_id, incoming)


async def buffer(message: Message) -> None:
    """ต่อท้าย buffer + เวลาข้อความล่าสุด = ตอนนี้ (reply_token อยู่ในข้อความ — worker ใช้ตัวล่าสุด)"""
    await redis.append_buffer(message)
    await redis.set_last_message_at(message.session_id, time.time())


async def start_buffering(session: Session) -> bool:
    """IDLE → BUFFERING · True = เพิ่งเปลี่ยน (ผู้ชนะคนเดียว) · False = BUFFERING / PROCESSING อยู่แล้ว"""
    return await redis.set_buffering_if_idle(session.session_id)


async def last_message_at(session_id: UUID) -> float:
    return await redis.get_last_message_at(session_id)


async def start_processing(session_id: UUID) -> None:
    """BUFFERING → PROCESSING"""
    await redis.set_processing(session_id)


async def read_buffer(session_id: UUID) -> list[Message]:
    return await redis.get_buffer(session_id)


async def read_history(session_id: UUID) -> list[ContextMessage]:
    """ที่คุยมาแล้วในใบนี้"""
    return await redis.get_history(session_id)


async def finish(session_id: UUID, buffer: list[Message], new_context: list[ContextMessage], answer: str) -> None:
    """บันทึกคำตอบบอท · ข้อความใน buffer → ตอบแล้ว · ต่อประวัติ · ล้าง buffer · state → IDLE"""
    await database.insert_bot_message(session_id, answer)
    await database.mark_answered([message.message_id for message in buffer])
    await redis.append_history(session_id, [*new_context, ContextMessage(role="assistant", type="text", content=answer)])
    await redis.clear_buffer(session_id)
    await redis.clear_state(session_id)


async def find_silent() -> list[Session]:
    """ใบ open ที่เงียบเกิน CLOSE_AFTER_MINUTES"""
    return await database.select_silent_sessions(CLOSE_AFTER_MINUTES)


async def start_closing(session: Session) -> bool:
    """IDLE → CLOSING · True = ได้ใบนี้ไปปิด · False = กำลังคุย / มีคนปิดอยู่แล้ว"""
    return await redis.set_closing_if_idle(session.session_id)


async def close(session: Session) -> bool:
    """PSQL ใบ → closed · สำเร็จ → ลบทุก key ของใบใน Redis · False = มีข้อความใหม่ ยังไม่เงียบ"""
    closed = await database.close_session(session.session_id, CLOSE_AFTER_MINUTES)
    if closed:
        await redis.clear_session(session.session_id)
    return closed


async def stop_closing(session: Session) -> None:
    """CLOSING → IDLE"""
    await redis.clear_state(session.session_id)


async def has_buffer(session: Session) -> bool:
    """มีข้อความรอใน buffer"""
    return await redis.buffer_length(session.session_id) > 0
