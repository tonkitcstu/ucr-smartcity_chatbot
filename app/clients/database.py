"""SQL ทั้งหมดอยู่ที่นี่"""

import json
from uuid import UUID

import asyncpg

from app.core.config import DATABASE_URL
from app.models.ai import AiConfig, AiModel, AiReply, Prompt
from app.models.attachment import Attachment
from app.models.context import ContextMessage
from app.models.message import IncomingMessage, Message, TranscriptMessage
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
    status: str = "ok",
    error: str | None = None,
) -> None:
    """request เก็บเป็น ContextMessage · response = คำตอบดิบ · status error เก็บเหตุไว้ใน error"""
    await pool.execute(
        """
        INSERT INTO ai_calls
            (session_id, ai_config_id, kind, request, response, input_tokens, output_tokens, status, error)
        VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7, $8, $9)
        """,
        session_id,
        ai_config_id,
        kind,
        json.dumps([message.model_dump() for message in request], ensure_ascii=False),
        reply.text,
        reply.input_tokens,
        reply.output_tokens,
        status,
        error,
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


async def select_silent_sessions(minutes: int) -> list[Session]:
    """ใบ open ที่ไม่มีข้อความเข้ามาเกิน minutes นาที"""
    rows = await pool.fetch(
        """
        SELECT session_id, user_id FROM sessions
        WHERE status = 'open' AND last_message_at < now() - make_interval(mins => $1)
        """,
        minutes,
    )
    return [Session(**row) for row in rows]


async def close_session(session_id: UUID, minutes: int) -> bool:
    """คำสั่งเดียว: ยัง open และยังเงียบเกิน minutes นาที → closed · True = ปิดแล้ว
    False = มีข้อความใหม่ขยับ last_message_at → ยังไม่เงียบ"""
    result = await pool.execute(
        """
        UPDATE sessions SET status = 'closed', closed_at = now()
        WHERE session_id = $1 AND status = 'open'
          AND last_message_at < now() - make_interval(mins => $2)
        """,
        session_id,
        minutes,
    )
    return result == "UPDATE 1"


async def select_transcript(session_id: UUID) -> list[TranscriptMessage]:
    """ข้อความทั้งใบ เรียงตามเวลา · รูปพ่วง attachment"""
    rows = await pool.fetch(
        """
        SELECT m.message_id, m.role, m.type, m.content, m.lat, m.lng, a.attachment_id, a.file_path
        FROM messages m LEFT JOIN attachments a USING (message_id)
        WHERE m.session_id = $1
        ORDER BY m.created_at
        """,
        session_id,
    )
    return [TranscriptMessage(**row) for row in rows]


async def insert_report(
    session_id: UUID, ai_config_id: UUID, desc: str, tags: list[str], lat: float | None, lng: float | None
) -> UUID:
    """started_at = เวลาเปิดใบ"""
    return await pool.fetchval(
        """
        INSERT INTO reports (session_id, ai_config_id, tags, lat, lng, "desc", started_at)
        SELECT $1, $2, $3, $4, $5, $6, started_at FROM sessions WHERE session_id = $1
        RETURNING report_id
        """,
        session_id,
        ai_config_id,
        tags,
        lat,
        lng,
        desc,
    )


async def link_attachments(report_id: UUID, attachment_ids: list[UUID]) -> None:
    await pool.execute(
        "UPDATE attachments SET report_id = $1 WHERE attachment_id = ANY($2::uuid[])", report_id, attachment_ids
    )


async def mark_analysed(session_id: UUID) -> None:
    await pool.execute("UPDATE sessions SET status = 'analysed' WHERE session_id = $1", session_id)


async def has_ai_config() -> bool:
    return await pool.fetchval("SELECT EXISTS (SELECT 1 FROM ai_configs)")


async def insert_ai_config(
    provider: str, chat_model: str, chat_prompt: str, analyser_model: str, analyser_prompt: str
) -> None:
    """transaction เดียว: models 2 แถว · prompts 2 แถว · ai_configs 1 แถวผูกทั้งสี่"""
    async with pool.acquire() as conn, conn.transaction():
        insert_model = "INSERT INTO models (provider, name) VALUES ($1, $2) RETURNING model_id"
        insert_prompt = "INSERT INTO prompts (prompt) VALUES ($1) RETURNING prompt_id"
        await conn.execute(
            """
            INSERT INTO ai_configs (chat_model_id, chat_prompt_id, analyzer_model_id, analyzer_prompt_id)
            VALUES ($1, $2, $3, $4)
            """,
            await conn.fetchval(insert_model, provider, chat_model),
            await conn.fetchval(insert_prompt, chat_prompt),
            await conn.fetchval(insert_model, provider, analyser_model),
            await conn.fetchval(insert_prompt, analyser_prompt),
        )
