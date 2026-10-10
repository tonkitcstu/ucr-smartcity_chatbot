"""SQL ทั้งหมดอยู่ที่นี่"""

import json
from uuid import UUID

import asyncpg

from app.core.config import DATABASE_URL
from app.models.ai import AiConfig, AiModel, AiReply, Prompt
from app.models.attachment import Attachment
from app.models.context import ContextMessage
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


async def select_line_user_id(session_id: UUID) -> str:
    """LINE ID ของเจ้าของใบ"""
    return await pool.fetchval(
        "SELECT u.line_user_id FROM sessions s JOIN users u USING (user_id) WHERE s.session_id = $1",
        session_id,
    )


async def insert_attachment(message_id: UUID, file_path: str) -> Attachment:
    row = await pool.fetchrow(
        """
        INSERT INTO attachments (message_id, type, file_path) VALUES ($1, 'image', $2)
        RETURNING attachment_id, message_id, file_path
        """,
        message_id,
        file_path,
    )
    return Attachment(**row)


async def select_latest_ai_config() -> AiConfig:
    row = await pool.fetchrow(
        """
        SELECT ai_config_id, chat_model_id, chat_prompt_id, analyzer_model_id, analyzer_prompt_id
        FROM ai_configs ORDER BY created_at DESC LIMIT 1
        """
    )
    return AiConfig(**row)


async def select_prompt(prompt_id: UUID) -> Prompt:
    row = await pool.fetchrow("SELECT prompt_id, prompt FROM prompts WHERE prompt_id = $1", prompt_id)
    return Prompt(**row)


async def select_model(model_id: UUID) -> AiModel:
    row = await pool.fetchrow("SELECT model_id, provider, name FROM models WHERE model_id = $1", model_id)
    return AiModel(**row)


async def insert_ai_call(
    session_id: UUID,
    ai_config_id: UUID,
    kind: str,
    request: list[ContextMessage],
    reply: AiReply,
) -> None:
    """เรียกสำเร็จ · request เก็บเป็น ContextMessage · response = คำตอบดิบ"""
    await pool.execute(
        """
        INSERT INTO ai_calls (session_id, ai_config_id, kind, request, response, input_tokens, output_tokens, status)
        VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7, 'ok')
        """,
        session_id,
        ai_config_id,
        kind,
        json.dumps([message.model_dump() for message in request], ensure_ascii=False),
        reply.text,
        reply.input_tokens,
        reply.output_tokens,
    )


async def insert_bot_message(session_id: UUID, content: str) -> None:
    """คำตอบบอท · assistant · ตอบแล้ว"""
    await pool.execute(
        """
        INSERT INTO messages (session_id, role, type, content, status)
        VALUES ($1, 'assistant', 'text', $2, 'answered')
        """,
        session_id,
        content,
    )


async def mark_answered(message_ids: list[UUID]) -> None:
    await pool.execute("UPDATE messages SET status = 'answered' WHERE message_id = ANY($1::uuid[])", message_ids)
