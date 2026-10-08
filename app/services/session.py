"""ใบของการคุย: หา/สร้างใบ, บันทึกข้อความ, buffer, state"""

import time

from app.clients import database, redis
from app.models.message import IncomingMessage, Message
from app.models.session import Session
from app.models.user import User


async def open_for(user: User) -> Session:
    """หาใบที่เปิดอยู่ ไม่มีก็สร้าง"""
    return await database.open_session(user.user_id)


async def save_message(session: Session, incoming: IncomingMessage) -> Message:
    """บันทึกเป็น ผู้แจ้ง · ยังไม่ตอบ"""
    return await database.insert_message(session.session_id, incoming)


async def buffer(message: Message) -> None:
    """ต่อท้าย buffer + เวลาข้อความล่าสุด = ตอนนี้ (reply_token อยู่ในข้อความ — worker ใช้ตัวล่าสุด)"""
    await redis.append_buffer(message)
    await redis.set_last_message_at(message.session_id, time.time())


async def start_buffering(session: Session) -> bool:
    """IDLE → BUFFERING · True = เพิ่งเปลี่ยน (ผู้ชนะคนเดียว) · False = BUFFERING / PROCESSING อยู่แล้ว"""
    return await redis.set_buffering_if_idle(session.session_id)
