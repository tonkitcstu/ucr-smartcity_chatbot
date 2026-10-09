"""H3 Controller รับรูปภายใน 3 วิ — S3 · spec ใน #151 · แบบ docs/designs/09-modules/h3-image.puml"""

import asyncio
import json

from tests.line_webhook import image_event, post_webhook, postback_event, text_event


async def accept_pdpa(client, user_id="U_a"):
    await post_webhook(client, postback_event("pdpa_accept", user_id=user_id, event_id="ev-accept"))


async def open_sessions(db):
    return await db.fetch("SELECT session_id FROM sessions WHERE status = 'open'")


async def buffer_of(redis, session_id):
    return [json.loads(item) for item in await redis.lrange(f"session:{session_id}:buffer", 0, -1)]


async def jobs(redis):
    return [json.loads(item) for item in await redis.lrange("jobs", 0, -1)]


def is_pdpa_card(reply):
    from app.services import pdpa

    _, messages = reply
    return messages == [pdpa.card()]


async def test_image_within_3s_joins_same_session_without_new_job(client, db, redis, replies):
    """1. พิมพ์ "น้ำท่วมหน้าบ้าน" แล้วส่งรูปตามมา (BUFFERING) → ใบเดิม · แถวรูป · buffer 2 · งานคุยยัง 1 งาน · บอทไม่ reply"""
    await accept_pdpa(client)

    first = await post_webhook(
        client,
        text_event("น้ำท่วมหน้าบ้าน", user_id="U_a", reply_token="rt-1", event_id="ev-1", message_id="m-1"),
    )
    second = await post_webhook(
        client,
        image_event(user_id="U_a", reply_token="rt-2", event_id="ev-2", message_id="img-2"),
    )

    assert first.status_code == 200
    assert second.status_code == 200

    sessions = await open_sessions(db)
    assert len(sessions) == 1
    session_id = str(sessions[0]["session_id"])

    assert await db.fetchval("SELECT count(*) FROM messages") == 2
    image = await db.fetchrow("SELECT * FROM messages WHERE type = 'image'")
    assert str(image["session_id"]) == session_id
    assert image["line_event_id"] == "ev-2"
    assert image["line_message_id"] == "img-2"
    assert image["role"] == "reporter"
    assert image["content"] is None
    assert image["status"] == "pending"

    buffer = await buffer_of(redis, session_id)
    assert len(buffer) == 2
    assert buffer[1]["type"] == "image"
    assert buffer[1]["line_message_id"] == "img-2"
    assert buffer[1]["reply_token"] == "rt-2"

    assert await redis.get(f"session:{session_id}:state") == "BUFFERING"
    assert await jobs(redis) == [{"kind": "chat", "session_id": session_id}]
    assert replies == []


async def test_image_first_opens_session_and_queues_one_chat_job(client, db, redis, replies):
    """2. ส่งรูปเป็นอย่างแรก (IDLE) → ใบใหม่ · แถวรูป 1 แถว · BUFFERING · งานคุย 1 งาน · บอทไม่ reply"""
    await accept_pdpa(client)

    response = await post_webhook(
        client,
        image_event(user_id="U_a", reply_token="rt-1", event_id="ev-1", message_id="img-1"),
    )

    assert response.status_code == 200

    sessions = await open_sessions(db)
    assert len(sessions) == 1
    session_id = str(sessions[0]["session_id"])

    image = await db.fetchrow("SELECT * FROM messages")
    assert str(image["session_id"]) == session_id
    assert image["type"] == "image"
    assert image["line_message_id"] == "img-1"

    assert await redis.get(f"session:{session_id}:state") == "BUFFERING"
    assert await jobs(redis) == [{"kind": "chat", "session_id": session_id}]
    assert replies == []


async def test_image_and_text_at_once_queue_only_one_chat_job(client, db, redis, replies):
    """3. รูปกับข้อความมาพร้อมกันตอน IDLE → ใบเดียว · ข้อความ 2 แถว · buffer 2 รายการ · งานคุย 1 งาน ไม่ใช่ 2"""
    await accept_pdpa(client)

    responses = await asyncio.gather(
        post_webhook(client, image_event(user_id="U_a", reply_token="rt-a", event_id="ev-a", message_id="img-a")),
        post_webhook(client, text_event("น้ำท่วม", user_id="U_a", reply_token="rt-b", event_id="ev-b", message_id="m-b")),
    )

    assert [r.status_code for r in responses] == [200, 200]

    sessions = await open_sessions(db)
    assert len(sessions) == 1
    session_id = str(sessions[0]["session_id"])

    assert await db.fetchval("SELECT count(*) FROM messages") == 2
    assert len(await buffer_of(redis, session_id)) == 2
    assert len(await jobs(redis)) == 1


async def test_three_images_in_one_webhook_buffer_in_order(client, db, redis, replies):
    """4. ส่งรูป 3 รูปทีเดียว (webhook เดียว 3 event) → แถวรูป 3 แถว ใบเดียว · buffer 3 รายการเรียงตามที่ส่ง · งานคุย 1 งาน"""
    await accept_pdpa(client)

    response = await post_webhook(
        client,
        image_event(user_id="U_a", reply_token="rt-1", event_id="ev-1", message_id="img-1"),
        image_event(user_id="U_a", reply_token="rt-2", event_id="ev-2", message_id="img-2"),
        image_event(user_id="U_a", reply_token="rt-3", event_id="ev-3", message_id="img-3"),
    )

    assert response.status_code == 200

    sessions = await open_sessions(db)
    assert len(sessions) == 1
    session_id = str(sessions[0]["session_id"])

    assert await db.fetchval("SELECT count(*) FROM messages WHERE type = 'image'") == 3

    buffer = await buffer_of(redis, session_id)
    assert [item["line_message_id"] for item in buffer] == ["img-1", "img-2", "img-3"]

    assert len(await jobs(redis)) == 1


async def test_image_before_accept_replies_card_and_stores_nothing(client, db, redis, replies):
    """5. ส่งรูปมาก่อนกดยอมรับ → ได้การ์ดอีกครั้ง · ไม่เก็บรูป · ไม่มี User · ไม่มีงาน (LC1)"""
    response = await post_webhook(client, image_event(user_id="U_a", reply_token="rt-5"))

    assert response.status_code == 200
    assert len(replies) == 1
    assert replies[0][0] == "rt-5"
    assert is_pdpa_card(replies[0])
    assert await db.fetchval("SELECT count(*) FROM users") == 0
    assert await db.fetchval("SELECT count(*) FROM messages") == 0
    assert await jobs(redis) == []
