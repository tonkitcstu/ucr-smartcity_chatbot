"""SQL ทั้งหมดอยู่ที่นี่"""

from uuid import UUID

import asyncpg

from app.core.config import DATABASE_URL
from app.models.message import IncomingMessage, Message
from app.models.session import Session
from app.models.user import User

pool: asyncpg.Pool | None = None


async def connect() -> None:
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL)


async def close() -> None:
    await pool.close()


async def select_user_by_line_id(line_user_id: str) -> User | None:
    row = await pool.fetchrow(
        "SELECT user_id, line_user_id, pdpa_accepted_at FROM users WHERE line_user_id = $1",
        line_user_id,
    )
    return User(**row) if row else None


async def insert_user(line_user_id: str) -> User:
    """สร้าง User พร้อมเวลายอมรับ · มีอยู่แล้วคืนแถวเดิม ไม่เขียนทับเวลา"""
    row = await pool.fetchrow(
        """
        INSERT INTO users (line_user_id, pdpa_accepted_at) VALUES ($1, now())
        ON CONFLICT (line_user_id) DO UPDATE SET line_user_id = EXCLUDED.line_user_id
        RETURNING user_id, line_user_id, pdpa_accepted_at
        """,
        line_user_id,
    )
    return User(**row)


async def open_session(user_id: UUID) -> Session:
    """เปิดใบใหม่ · มีใบเปิดอยู่แล้วคืนใบเดิม · ทั้งสองทาง last_message_at = now()"""
    row = await pool.fetchrow(
        """
        INSERT INTO sessions (user_id) VALUES ($1)
        ON CONFLICT (user_id) WHERE status = 'open' DO UPDATE SET last_message_at = now()
        RETURNING session_id, user_id
        """,
        user_id,
    )
    return Session(**row)


async def insert_message(session_id: UUID, incoming: IncomingMessage) -> Message:
    """บันทึกเป็น user (ผู้แจ้ง) · ยังไม่ตอบ"""
    message_id = await pool.fetchval(
        """
        INSERT INTO messages (session_id, line_event_id, line_message_id, role, type, content)
        VALUES ($1, $2, $3, 'user', $4, $5)
        RETURNING message_id
        """,
        session_id,
        incoming.line_event_id,
        incoming.line_message_id,
        incoming.type,
        incoming.content,
    )
    return Message(**incoming.model_dump(), message_id=message_id, session_id=session_id)
