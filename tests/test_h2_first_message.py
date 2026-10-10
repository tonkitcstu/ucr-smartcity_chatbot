"""H2 Controller รับข้อความแรก — S2 · spec ใน #150 · แบบ docs/designs/09-modules/h2-first-message.puml"""

import asyncio
import json

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
