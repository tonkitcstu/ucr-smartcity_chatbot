"""SQL ทั้งหมดอยู่ที่นี่"""

import asyncpg

from app.core.config import DATABASE_URL
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
