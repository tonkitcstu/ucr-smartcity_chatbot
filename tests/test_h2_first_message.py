"""H2 Controller รับข้อความแรก — S2 · spec ใน #150 · แบบ docs/designs/09-modules/h2-first-message.puml"""

import asyncio
import json

import pytest

from tests.line_webhook import post_webhook, postback_event, text_event


async def accept_pdpa(client, user_id="U_a"):
    await post_webhook(client, postback_event("pdpa_accept", user_id=user_id, event_id="ev-accept"))


async def open_sessions(db):
    return await db.fetch("SELECT session_id, last_message_at FROM sessions WHERE status = 'open'")


async def buffer_of(redis, session_id):
    return [json.loads(item) for item in await redis.lrange(f"session:{session_id}:buffer", 0, -1)]


async def jobs(redis):
    return [json.loads(item) for item in await redis.lrange("jobs", 0, -1)]


async def test_first_message_opens_session_and_queues_one_chat_job(client, db, redis, replies):
    """1. พิมพ์ "น้ำท่วมหน้าบ้าน" ครั้งแรก → ใบใหม่ · ข้อความยังไม่ตอบ · buffer · BUFFERING · งานคุย 1 งาน · บอทไม่ reply"""
    await accept_pdpa(client)

    response = await post_webhook(
        client,
        text_event("น้ำท่วมหน้าบ้าน", user_id="U_a", reply_token="rt-1", event_id="ev-1", message_id="m-1"),
    )

    assert response.status_code == 200

    sessions = await open_sessions(db)
    assert len(sessions) == 1
    session_id = str(sessions[0]["session_id"])

    message = await db.fetchrow("SELECT * FROM messages")
    assert str(message["session_id"]) == session_id
    assert message["line_event_id"] == "ev-1"
    assert message["line_message_id"] == "m-1"
    assert message["role"] == "user"
    assert message["type"] == "text"
    assert message["content"] == "น้ำท่วมหน้าบ้าน"
    assert message["status"] == "pending"

    buffer = await buffer_of(redis, session_id)
    assert len(buffer) == 1
    assert buffer[0]["content"] == "น้ำท่วมหน้าบ้าน"
    assert buffer[0]["reply_token"] == "rt-1"

    assert await redis.exists(f"session:{session_id}:last_message_at")
    assert await redis.get(f"session:{session_id}:state") == "BUFFERING"

    assert await jobs(redis) == [{"kind": "chat", "session_id": session_id}]

    assert replies == []


async def test_two_messages_at_once_queue_only_one_chat_job(client, db, redis, replies):
    """2. ข้อความ 2 อันมาพร้อมกันตอน IDLE → ใบเดียว · ข้อความ 2 แถว · buffer 2 รายการ · งานคุย 1 งาน ไม่ใช่ 2"""
    await accept_pdpa(client)

    responses = await asyncio.gather(
        post_webhook(client, text_event("น้ำท่วม", user_id="U_a", reply_token="rt-a", event_id="ev-a", message_id="m-a")),
        post_webhook(client, text_event("หน้าบ้าน", user_id="U_a", reply_token="rt-b", event_id="ev-b", message_id="m-b")),
    )

    assert [r.status_code for r in responses] == [200, 200]

    sessions = await open_sessions(db)
    assert len(sessions) == 1
    session_id = str(sessions[0]["session_id"])

    assert await db.fetchval("SELECT count(*) FROM messages") == 2
    assert len(await buffer_of(redis, session_id)) == 2
    assert len(await jobs(redis)) == 1


async def test_next_message_after_bot_answered_reuses_open_session(client, db, redis, replies):
    """3. พิมพ์ข้อความถัดไปหลังบอทตอบแล้ว (IDLE แต่ใบยังเปิด) → ใบเดิม · last_message_at ขยับ · งานคุยใหม่ 1 งาน"""
    await accept_pdpa(client)
    await post_webhook(client, text_event("น้ำท่วมหน้าบ้าน", user_id="U_a", event_id="ev-1", message_id="m-1"))
    [first] = await open_sessions(db)
    session_id = str(first["session_id"])

    # จำลอง worker ตอบเสร็จ (H4): หยิบงานไปแล้ว · ล้าง buffer · state กลับเป็น IDLE (ไม่มี key)
    await redis.delete("jobs", f"session:{session_id}:buffer", f"session:{session_id}:state")

    await post_webhook(client, text_event("ตอนนี้น้ำลดแล้ว", user_id="U_a", event_id="ev-2", message_id="m-2"))

    sessions = await open_sessions(db)
    assert len(sessions) == 1
    assert str(sessions[0]["session_id"]) == session_id
    assert sessions[0]["last_message_at"] > first["last_message_at"]
    assert await jobs(redis) == [{"kind": "chat", "session_id": session_id}]


# --- #239 ① เพดาน token ต่อผู้แจ้งต่อวัน — T10 · spec ใน #239 · แบบ docs/designs/09-modules/239-user-token-limit.puml ---

LIMIT = 100


async def add_config_with_limit(db, limit):
    """ai_configs แถวใหม่ — model และ prompt เหมือนแถวที่ใช้อยู่ · เพดาน token ต่อผู้แจ้งต่อวันตามที่ให้ · ยังไม่ถูกเลือก"""
    return await db.fetchval(
        """
        INSERT INTO ai_configs
            (chat_model_id, chat_prompt_id, analyzer_model_id, analyzer_prompt_id, user_daily_token_limit)
        SELECT chat_model_id, chat_prompt_id, analyzer_model_id, analyzer_prompt_id, $1
        FROM ai_configs WHERE is_active
        RETURNING ai_config_id
        """,
        limit,
    )


async def choose(db, ai_config_id):
    """เลือกแถวที่ใช้ตามแบบ #242 — ปลดแถวเดิมก่อน แล้วตั้งแถวใหม่ ใน transaction เดียว"""
    async with db.transaction():
        await db.execute("UPDATE ai_configs SET is_active = false WHERE is_active")
        await db.execute("UPDATE ai_configs SET is_active = true WHERE ai_config_id = $1", ai_config_id)


@pytest.fixture
async def daily_limit(client, db):
    """เลือกแถวที่เพดาน = LIMIT · จบ test คืนแถวที่เลือกเดิม (ai_configs ไม่ถูกล้างระหว่าง test)"""
    before = await db.fetchval("SELECT ai_config_id FROM ai_configs WHERE is_active")
    limited = await add_config_with_limit(db, LIMIT)
    await choose(db, limited)
    yield limited
    await choose(db, before)


async def spend(db, line_user_id, input_tokens, output_tokens, kind="communicator", yesterday=False):
    """ผู้แจ้งคนนี้ใช้ token ไปแล้ว — ใบที่วิเคราะห์แล้ว 1 ใบ + ai_calls 1 แถว
    yesterday = หนึ่งนาทีก่อนเที่ยงคืนเวลาไทยของวันนี้ · ไม่ใส่ = ตอนนี้"""
    user_id = await db.fetchval("SELECT user_id FROM users WHERE line_user_id = $1", line_user_id)
    session_id = await db.fetchval(
        "INSERT INTO sessions (user_id, status, closed_at) VALUES ($1, 'analysed', now()) RETURNING session_id",
        user_id,
    )
    at = (
        "date_trunc('day', now() AT TIME ZONE 'Asia/Bangkok') AT TIME ZONE 'Asia/Bangkok' - interval '1 minute'"
        if yesterday
        else "now()"
    )
    await db.execute(
        f"""
        INSERT INTO ai_calls (session_id, ai_config_id, kind, request, input_tokens, output_tokens, status, created_at)
        SELECT $1, ai_config_id, $2, '[]', $3, $4, 'ok', {at} FROM ai_configs WHERE is_active
        """,
        session_id,
        kind,
        input_tokens,
        output_tokens,
    )


async def state_of(redis, session_id):
    return await redis.get(f"session:{session_id}:state")


def fixed_reply_texts():
    """ถ้อยคำของข้อความแข็ง — อ่านจากโค้ด ไม่เขียนซ้ำใน test"""
    from app.services import quota

    return [quota.limit_reached_message().text]


async def test_under_daily_token_limit_goes_the_usual_way(client, db, redis, replies, daily_limit):
    """239-1. ยอด token วันนี้ต่ำกว่าเพดาน → ทางเดิม: buffer · BUFFERING · งานคุย 1 งาน · บอทไม่ reply"""
    await accept_pdpa(client)
    await spend(db, "U_a", 60, 39)

    await post_webhook(client, text_event("น้ำท่วมหน้าบ้าน", user_id="U_a", reply_token="rt-1", event_id="ev-1"))

    [session] = await open_sessions(db)
    session_id = str(session["session_id"])
    assert [item["content"] for item in await buffer_of(redis, session_id)] == ["น้ำท่วมหน้าบ้าน"]
    assert await state_of(redis, session_id) == "BUFFERING"
    assert await jobs(redis) == [{"kind": "chat", "session_id": session_id}]
    assert replies == []


async def test_reaching_daily_token_limit_gets_the_fixed_reply(client, db, redis, replies, daily_limit):
    """239-2. ยอด token วันนี้เท่ากับเพดาน → บันทึกข้อความ · reply ข้อความแข็งด้วย token ของข้อความนี้
    buffer ว่าง · ไม่มี state · ไม่มีงานคุย"""
    await accept_pdpa(client)
    await spend(db, "U_a", 60, 40)

    await post_webhook(client, text_event("น้ำท่วมอีกแล้ว", user_id="U_a", reply_token="rt-1", event_id="ev-1"))

    [session] = await open_sessions(db)
    session_id = str(session["session_id"])
    assert await db.fetchval("SELECT content FROM messages WHERE line_event_id = 'ev-1'") == "น้ำท่วมอีกแล้ว"
    [(reply_token, messages)] = replies
    assert reply_token == "rt-1"
    assert [message.text for message in messages] == fixed_reply_texts()
    assert await buffer_of(redis, session_id) == []
    assert await state_of(redis, session_id) is None
    assert await jobs(redis) == []


async def test_tokens_from_yesterday_are_not_counted(client, db, redis, replies, daily_limit):
    """239-3. token ที่ใช้เมื่อวาน (ก่อนเที่ยงคืนเวลาไทย) เกินเพดาน → ไม่นับ — ทางเดิม"""
    await accept_pdpa(client)
    await spend(db, "U_a", 500, 0, yesterday=True)

    await post_webhook(client, text_event("น้ำท่วมหน้าบ้าน", user_id="U_a", event_id="ev-1"))

    assert len(await jobs(redis)) == 1
    assert replies == []


async def test_tokens_of_another_reporter_are_not_counted(client, db, redis, replies, daily_limit):
    """239-4. token ของผู้แจ้งคนอื่นเกินเพดาน → ไม่นับ — ทางเดิม"""
    await accept_pdpa(client, user_id="U_a")
    await post_webhook(client, postback_event("pdpa_accept", user_id="U_b", event_id="ev-accept-b"))
    await spend(db, "U_b", 500, 0)

    await post_webhook(client, text_event("น้ำท่วมหน้าบ้าน", user_id="U_a", event_id="ev-1"))

    assert len(await jobs(redis)) == 1
    assert replies == []


async def test_analyser_tokens_count_too(client, db, redis, replies, daily_limit):
    """239-5. token ของตัวคุยยังไม่ถึง แต่รวมตัววิเคราะห์แล้วถึงเพดาน → นับรวม — ข้อความแข็ง"""
    await accept_pdpa(client)
    await spend(db, "U_a", 40, 10, kind="communicator")
    await spend(db, "U_a", 45, 5, kind="analyser")

    await post_webhook(client, text_event("น้ำท่วมอีกแล้ว", user_id="U_a", reply_token="rt-1", event_id="ev-1"))

    [(_, messages)] = replies
    assert [message.text for message in messages] == fixed_reply_texts()
    assert await jobs(redis) == []


async def test_limit_comes_from_the_chosen_config(client, db, redis, replies, daily_limit):
    """239-6. สลับไปแถวที่เพดานต่ำกว่ายอด → ข้อความแข็ง · สลับไปแถวที่เพดานสูงกว่ายอด → ทางเดิม"""
    await accept_pdpa(client)
    await spend(db, "U_a", 150, 0)

    await post_webhook(client, text_event("น้ำท่วมอีกแล้ว", user_id="U_a", reply_token="rt-1", event_id="ev-1"))
    await choose(db, await add_config_with_limit(db, 1000))
    await post_webhook(client, text_event("ยังท่วมอยู่", user_id="U_a", reply_token="rt-2", event_id="ev-2"))

    [(reply_token, messages)] = replies
    assert reply_token == "rt-1"
    assert [message.text for message in messages] == fixed_reply_texts()
    [session] = await open_sessions(db)
    assert await jobs(redis) == [{"kind": "chat", "session_id": str(session["session_id"])}]


async def test_message_while_waiting_for_silence_gets_its_own_fixed_reply(client, db, redis, replies, daily_limit):
    """239-7. ใบกำลังรอเงียบ (BUFFERING) แล้วข้อความใหม่เข้ามาตอนยอดถึงเพดาน → ข้อความแข็งด้วย token ของข้อความใหม่
    buffer ของรอบนั้นไม่มีข้อความใหม่ · งานคุยไม่เพิ่ม"""
    await accept_pdpa(client)
    await post_webhook(client, text_event("น้ำท่วมหน้าบ้าน", user_id="U_a", reply_token="rt-1", event_id="ev-1"))
    [session] = await open_sessions(db)
    session_id = str(session["session_id"])
    await spend(db, "U_a", 100, 0)

    await post_webhook(client, text_event("สูงประมาณเข่า", user_id="U_a", reply_token="rt-2", event_id="ev-2"))

    [(reply_token, messages)] = replies
    assert reply_token == "rt-2"
    assert [message.text for message in messages] == fixed_reply_texts()
    assert [item["content"] for item in await buffer_of(redis, session_id)] == ["น้ำท่วมหน้าบ้าน"]
    assert await state_of(redis, session_id) == "BUFFERING"
    assert await jobs(redis) == [{"kind": "chat", "session_id": session_id}]
