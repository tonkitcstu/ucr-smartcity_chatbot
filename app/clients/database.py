"""SQL ทั้งหมดอยู่ที่นี่"""

import json
from datetime import date
from uuid import UUID

import asyncpg

from app.core.config import DATABASE_URL
from app.models.ai import AiConfig, AiModel, AiReply, Prompt
from app.models.attachment import Attachment
from app.models.answer import ChatAnswer
from app.models.broadcast import Broadcast
from app.models.context import ContextMessage
from app.models.line import IncomingMessage
from app.models.message import Message, TranscriptMessage
from app.models.report import ReportDraft, ReportRow
from app.models.session import Session
from app.models.user import User

pool: asyncpg.Pool | None = None


async def connect() -> None:
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL)


async def close() -> None:
    await pool.close()


async def ping() -> bool:
    """PSQL ตอบ → True · ต่อไม่ได้ / error → False"""
    try:
        await pool.fetchval("SELECT 1")
        return True
    except Exception:
        return False


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
        INSERT INTO messages (session_id, line_event_id, line_message_id, role, type, content, lat, lng)
        VALUES ($1, $2, $3, 'user', $4, $5, $6, $7)
        RETURNING message_id
        """,
        session_id,
        incoming.line_event_id,
        incoming.line_message_id,
        incoming.type,
        incoming.content,
        incoming.lat,
        incoming.lng,
    )
    return Message(**incoming.model_dump(), message_id=message_id, session_id=session_id)


async def select_line_user_id(session_id: UUID) -> str:
    """LINE ID ของเจ้าของใบ"""
    return await pool.fetchval(
        "SELECT u.line_user_id FROM sessions s JOIN users u USING (user_id) WHERE s.session_id = $1",
        session_id,
    )


async def sum_user_tokens_today(user_id: UUID) -> int:
    """token (input + output) ของ ai_calls ทุกใบของผู้แจ้งคนนี้ เฉพาะตัวคุย · วันนี้ตามเวลาไทย · แถวที่ไม่มีจำนวนนับเป็น 0"""
    return await pool.fetchval(
        """
        SELECT coalesce(sum(coalesce(c.input_tokens, 0) + coalesce(c.output_tokens, 0)), 0)
        FROM ai_calls c JOIN sessions s USING (session_id)
        WHERE s.user_id = $1
          AND c.kind = 'communicator'
          AND (c.created_at AT TIME ZONE 'Asia/Bangkok')::date = (now() AT TIME ZONE 'Asia/Bangkok')::date
        """,
        user_id,
    )


async def sum_system_tokens_today() -> int:
    """token (input + output) ของ ai_calls ทุกแถวของผู้แจ้งทุกคน เฉพาะตัวคุย · วันนี้ตามเวลาไทย · แถวที่ไม่มีจำนวนนับเป็น 0"""
    return await pool.fetchval(
        """
        SELECT coalesce(sum(coalesce(input_tokens, 0) + coalesce(output_tokens, 0)), 0)
        FROM ai_calls
        WHERE kind = 'communicator'
          AND (created_at AT TIME ZONE 'Asia/Bangkok')::date = (now() AT TIME ZONE 'Asia/Bangkok')::date
        """
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


async def select_active_ai_config() -> AiConfig:
    """แถวที่ is_active = true — schema กันไว้ให้มีได้แถวเดียว"""
    row = await pool.fetchrow(
        """
        SELECT ai_config_id, chat_model_id, chat_prompt_id, analyzer_model_id, analyzer_prompt_id,
               user_daily_token_limit, session_buffer_limit, system_daily_token_limit
        FROM ai_configs WHERE is_active
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
    """request เก็บเป็น ContextMessage · response = คำตอบดิบ · status warning / error เก็บเหตุไว้ใน error"""
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


async def mark_skipped(message_ids: list[UUID]) -> None:
    await pool.execute("UPDATE messages SET status = 'skipped' WHERE message_id = ANY($1::uuid[])", message_ids)


# ใบ open ที่ไม่มีข้อความเข้ามาเกิน minutes นาที
# ใบที่บอททักไปก่อนและผู้แจ้งยังไม่ตอบสักข้อความ รอนานกว่า คือ broadcast_wait_hours ชั่วโมง
async def select_silent_sessions(minutes: int, broadcast_wait_hours: int) -> list[Session]:
    rows = await pool.fetch(
        """
        SELECT s.session_id, s.user_id FROM sessions s
        WHERE s.status = 'open' AND s.last_message_at < now() - make_interval(mins => $1)
          AND (
              s.broadcast_id IS NULL
              OR EXISTS (SELECT 1 FROM messages m WHERE m.session_id = s.session_id AND m.role = 'user')
              OR s.last_message_at < now() - make_interval(hours => $2)
          )
        """,
        minutes,
        broadcast_wait_hours,
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
        SELECT m.message_id, m.role, m.type, m.content, m.lat, m.lng, m.status, a.attachment_id, a.file_path
        FROM messages m LEFT JOIN attachments a USING (message_id)
        WHERE m.session_id = $1
        ORDER BY m.created_at
        """,
        session_id,
    )
    return [TranscriptMessage(**row) for row in rows]


# ช่องที่ AI ร่างมาเก็บตามนั้น · lat/lng แปลงจากเลขป้ายแล้ว · started_at = เวลาเปิดใบ
async def insert_report(
    session_id: UUID, ai_config_id: UUID, draft: ReportDraft, lat: float | None, lng: float | None
) -> UUID:
    return await pool.fetchval(
        """
        INSERT INTO reports
            (session_id, ai_config_id, tags, lat, lng, "desc", severity, affected_groups, time_periods, place,
             started_at)
        SELECT $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, started_at FROM sessions WHERE session_id = $1
        RETURNING report_id
        """,
        session_id,
        ai_config_id,
        draft.tags,
        lat,
        lng,
        draft.desc,
        draft.severity,
        draft.affected_groups,
        draft.time_periods,
        draft.place,
    )


async def link_attachments(report_id: UUID, attachment_ids: list[UUID]) -> None:
    await pool.execute(
        "UPDATE attachments SET report_id = $1 WHERE attachment_id = ANY($2::uuid[])", report_id, attachment_ids
    )


async def mark_analysed(session_id: UUID) -> None:
    await pool.execute("UPDATE sessions SET status = 'analysed' WHERE session_id = $1", session_id)


async def has_active_ai_config() -> bool:
    """มีแถวที่ถูกเลือกไหม — มีแถวแต่ไม่มีแถวไหนถูกเลือก นับเป็นไม่มี"""
    return await pool.fetchval("SELECT EXISTS (SELECT 1 FROM ai_configs WHERE is_active)")


async def insert_active_ai_config(
    provider: str, chat_model: str, chat_prompt: str, analyser_model: str, analyser_prompt: str
) -> None:
    """transaction เดียว: models 2 แถว · prompts 2 แถว · ai_configs 1 แถวผูกทั้งสี่ เป็นแถวที่ใช้ทันที"""
    async with pool.acquire() as conn, conn.transaction():
        insert_model = "INSERT INTO models (provider, name) VALUES ($1, $2) RETURNING model_id"
        insert_prompt = "INSERT INTO prompts (prompt) VALUES ($1) RETURNING prompt_id"
        await conn.execute(
            """
            INSERT INTO ai_configs (chat_model_id, chat_prompt_id, analyzer_model_id, analyzer_prompt_id, is_active)
            VALUES ($1, $2, $3, $4, true)
            """,
            await conn.fetchval(insert_model, provider, chat_model),
            await conn.fetchval(insert_prompt, chat_prompt),
            await conn.fetchval(insert_model, provider, analyser_model),
            await conn.fetchval(insert_prompt, analyser_prompt),
        )


# รายงานใหม่ → เก่า + รูปของแต่ละใบ · date นับวันตามเวลาไทย · tag ต้องตรงทั้งคำ
# ช่องของรายงานหนึ่งใบ + รูปที่ผูกกับมัน · ใช้ร่วมกันทั้งรายการและใบเดียว · ต่อท้ายด้วย WHERE ... GROUP BY
SELECT_REPORT = """
    SELECT r.report_id, r.session_id, s.user_id, r."desc", coalesce(r.tags, '{}') AS tags,
           r.severity, r.affected_groups, r.time_periods, r.place, r.lat, r.lng,
           coalesce(array_agg(a.attachment_id ORDER BY a.created_at) FILTER (WHERE a.attachment_id IS NOT NULL),
                    '{}') AS attachment_ids,
           r.started_at, r.created_at
    FROM reports r
    JOIN sessions s ON s.session_id = r.session_id
    LEFT JOIN attachments a ON a.report_id = r.report_id
"""


# ตัวกรองที่เป็น None = ไม่กรอง · วันทั้งสามตัวนับจาก created_at ตามเวลาไทย
async def select_reports(
    date: date | None,
    start_date: date | None,
    end_date: date | None,
    tag: str | None,
    severity: str | None,
    limit: int,
) -> list[ReportRow]:
    rows = await pool.fetch(
        SELECT_REPORT
        + """
        WHERE ($1::date IS NULL OR (r.created_at AT TIME ZONE 'Asia/Bangkok')::date = $1)
          AND ($2::date IS NULL OR (r.created_at AT TIME ZONE 'Asia/Bangkok')::date >= $2)
          AND ($3::date IS NULL OR (r.created_at AT TIME ZONE 'Asia/Bangkok')::date <= $3)
          AND ($4::text IS NULL OR $4 = ANY (r.tags))
          AND ($5::text IS NULL OR r.severity = $5)
        GROUP BY r.report_id, s.user_id
        ORDER BY r.created_at DESC
        LIMIT $6
        """,
        date,
        start_date,
        end_date,
        tag,
        severity,
        limit,
    )
    return [ReportRow(**row) for row in rows]


async def select_report(report_id: UUID) -> ReportRow | None:
    row = await pool.fetchrow(SELECT_REPORT + " WHERE r.report_id = $1 GROUP BY r.report_id, s.user_id", report_id)
    return ReportRow(**row) if row else None


async def select_attachment_path(attachment_id: UUID) -> str | None:
    return await pool.fetchval("SELECT file_path FROM attachments WHERE attachment_id = $1", attachment_id)


async def select_broadcast(day: date) -> Broadcast | None:
    row = await pool.fetchrow(
        "SELECT broadcast_id, forecast_date, reason, status, greeting FROM broadcasts WHERE forecast_date = $1", day
    )
    return to_broadcast(row) if row else None


# greeting มาจาก jsonb เป็นข้อความ JSON
def to_broadcast(row) -> Broadcast:
    greeting = row["greeting"]
    return Broadcast(**{**row, "greeting": ChatAnswer.model_validate_json(greeting) if greeting else None})


# จดพยากรณ์ของวันนั้น · มีเหตุให้ทัก → scheduled · ไม่มี → skipped
# วันนั้นมีแถวแล้ว (อีก process จดไปก่อน) → คืนแถวเดิม ไม่เขียนทับ
async def insert_broadcast(day: date, reason: str | None) -> Broadcast:
    row = await pool.fetchrow(
        """
        INSERT INTO broadcasts (forecast_date, reason, status)
        VALUES ($1, $2, CASE WHEN $2::text IS NULL THEN 'skipped' ELSE 'scheduled' END)
        ON CONFLICT (forecast_date) DO UPDATE SET forecast_date = EXCLUDED.forecast_date
        RETURNING broadcast_id, forecast_date, reason, status, greeting
        """,
        day,
        reason,
    )
    return to_broadcast(row)


async def save_broadcast_greeting(broadcast_id: UUID, greeting: ChatAnswer) -> None:
    await pool.execute(
        "UPDATE broadcasts SET greeting = $2::jsonb WHERE broadcast_id = $1", broadcast_id, greeting.model_dump_json()
    )


async def mark_broadcast_sent(broadcast_id: UUID) -> None:
    await pool.execute("UPDATE broadcasts SET status = 'sent', sent_at = now() WHERE broadcast_id = $1", broadcast_id)


# scheduled → expired · แถวที่ทักครบแล้วไม่แตะ
async def mark_broadcast_expired(broadcast_id: UUID) -> None:
    await pool.execute(
        "UPDATE broadcasts SET status = 'expired' WHERE broadcast_id = $1 AND status = 'scheduled'", broadcast_id
    )


# ผู้แจ้งทุกคนที่ยอมรับ PDPA แล้ว เรียงตามคนที่มาก่อน
# ใบของการทักครั้งนี้ที่เปิดไปแล้ว = จำนวนคนที่ได้ไปแล้ว
async def count_broadcast_sessions(broadcast_id: UUID) -> int:
    return await pool.fetchval("SELECT count(*) FROM sessions WHERE broadcast_id = $1", broadcast_id)


# สุ่มคนที่ทักได้ ไม่เกิน count คน · ยังติดตามบอท · ไม่มีใบเปิดอยู่ · ยังไม่ได้ใบของการทักครั้งนี้
async def select_broadcast_recipients(broadcast_id: UUID, count: int) -> list[User]:
    rows = await pool.fetch(
        """
        SELECT u.user_id, u.line_user_id, u.pdpa_accepted_at
        FROM users u
        WHERE u.blocked_at IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM sessions s
              WHERE s.user_id = u.user_id AND (s.status = 'open' OR s.broadcast_id = $1)
          )
        ORDER BY random()
        LIMIT $2
        """,
        broadcast_id,
        count,
    )
    return [User(**row) for row in rows]


# LINE unfollow · ยังไม่ยอมรับ PDPA ไม่มีแถว ไม่มีอะไรให้แก้
async def mark_user_blocked(line_user_id: str) -> None:
    await pool.execute("UPDATE users SET blocked_at = now() WHERE line_user_id = $1", line_user_id)


# LINE follow
async def mark_user_following(line_user_id: str) -> None:
    await pool.execute("UPDATE users SET blocked_at = NULL WHERE line_user_id = $1", line_user_id)


# เปิดใบใหม่ที่ติดป้ายว่าบอททักไปก่อน · คำสั่งเดียว ชน index ตัวไหนก็ได้ None ไม่แตะใบเดิม
#   ชน sessions_one_open_per_user = ผู้แจ้งมีใบเปิดอยู่แล้ว (กำลังคุยกันอยู่)
#   ชน sessions_one_per_broadcast = ผู้แจ้งได้ใบของการทักครั้งนี้ไปแล้ว
async def open_broadcast_session(user_id: UUID, broadcast_id: UUID) -> Session | None:
    row = await pool.fetchrow(
        """
        INSERT INTO sessions (user_id, broadcast_id) VALUES ($1, $2)
        ON CONFLICT DO NOTHING
        RETURNING session_id, user_id
        """,
        user_id,
        broadcast_id,
    )
    return Session(**row) if row else None
