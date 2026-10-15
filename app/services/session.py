"""ใบของการคุย: หา/สร้างใบ, บันทึกข้อความ, buffer, ข้ามข้อความตอนพักใบ, ประวัติที่คุยมา, ปิดใบ, บทสนทนาทั้งใบ
state ของใบอยู่ที่ state.py"""

import time
from uuid import UUID

from app.clients import database, redis
from app.core.config import CLOSE_AFTER_MINUTES
from app.models.context import ContextMessage
from app.models.line import IncomingMessage
from app.models.message import Message, TranscriptMessage
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


async def skip(session: Session, message: Message) -> None:
    """ข้อความที่ค้างใน buffer และข้อความนี้ → skipped · ล้าง buffer — ใบถูกพัก ไม่ส่งให้ AI (#239)"""
    buffered = await redis.get_buffer(session.session_id)
    await database.mark_skipped([item.message_id for item in [*buffered, message]])
    await redis.clear_buffer(session.session_id)


async def last_message_at(session_id: UUID) -> float:
    return await redis.get_last_message_at(session_id)


async def read_buffer(session_id: UUID) -> list[Message]:
    return await redis.get_buffer(session_id)


async def read_history(session_id: UUID) -> list[ContextMessage]:
    """ที่คุยมาแล้วในใบนี้"""
    return await redis.get_history(session_id)


async def finish(
    session_id: UUID, buffer: list[Message], new_context: list[ContextMessage], answers: list[str]
) -> None:
    """บันทึกคำตอบบอททีละข้อความตามลำดับ · ข้อความใน buffer → ตอบแล้ว · ต่อประวัติ ข้อความละรายการ · ล้าง buffer"""
    for answer in answers:
        await database.insert_bot_message(session_id, answer)
    await database.mark_answered([message.message_id for message in buffer])
    bot_context = [ContextMessage(role="assistant", type="text", content=answer) for answer in answers]
    await redis.append_history(session_id, [*new_context, *bot_context])
    await redis.clear_buffer(session_id)


async def find_silent() -> list[Session]:
    """ใบ open ที่เงียบเกิน CLOSE_AFTER_MINUTES"""
    return await database.select_silent_sessions(CLOSE_AFTER_MINUTES)


async def close(session: Session) -> bool:
    """PSQL ใบ → closed · สำเร็จ → ลบทุก key ของใบใน Redis · False = มีข้อความใหม่ ยังไม่เงียบ"""
    closed = await database.close_session(session.session_id, CLOSE_AFTER_MINUTES)
    if closed:
        await redis.clear_session(session.session_id)
    return closed


async def has_buffer(session: Session) -> bool:
    """มีข้อความรอใน buffer"""
    return await redis.buffer_length(session.session_id) > 0


async def read_transcript(session_id: UUID) -> list[TranscriptMessage]:
    """ข้อความทั้งใบจาก PSQL เรียงตามเวลา รวมข้อความ skipped — แดชบอร์ดเห็นทุกข้อความ (S23)"""
    return await database.select_transcript(session_id)


async def read_transcript_for_analysis(session_id: UUID) -> list[TranscriptMessage]:
    """บทสนทนาทั้งใบ ยกเว้นข้อความ skipped (#239) · ตัววิเคราะห์และ report.save ใช้ชุดนี้ชุดเดียวกัน เลขป้ายจึงตรงกัน"""
    return [message for message in await database.select_transcript(session_id) if message.status != "skipped"]


async def mark_analysed(session_id: UUID) -> None:
    await database.mark_analysed(session_id)
