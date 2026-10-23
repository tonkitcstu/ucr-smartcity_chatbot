"""H3 Controller รับรูปภายใน 3 วิ — S3 · spec ใน #151 · แบบ docs/designs/09-modules/h3-image.puml"""

import asyncio
import json

import pytest

from tests.line_webhook import (
    accept_pdpa,
    MESSAGE_STICKER_KEYWORDS,
    MESSAGE_STICKER_TEXT,
    PIN,
    PIN_ADDRESS,
    PIN_TITLE,
    STICKER_KEYWORDS,
    audio_event,
    image_event,
    location_event,
    post_webhook,
    sticker_event,
    text_event,
)


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
    assert image["role"] == "user"
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


# --- H9 รับตำแหน่งและสติกเกอร์ — S4 S13 · spec ใน #219 · แบบ docs/designs/09-modules/h9-location-sticker.puml ---


async def test_pin_first_opens_session_and_queues_one_chat_job(client, db, redis, replies):
    """H9-1. ปักหมุดเป็นอย่างแรก (IDLE) → ใบใหม่ · แถว location มี lat lng · content ว่าง · buffer · BUFFERING · งานคุย 1 งาน · บอทไม่ reply"""
    await accept_pdpa(client)

    response = await post_webhook(
        client,
        location_event(
            *PIN, user_id="U_a", reply_token="rt-1", event_id="ev-1", message_id="loc-1",
            title=PIN_TITLE, address=PIN_ADDRESS,
        ),
    )

    assert response.status_code == 200

    sessions = await open_sessions(db)
    assert len(sessions) == 1
    session_id = str(sessions[0]["session_id"])

    pin = await db.fetchrow("SELECT * FROM messages")
    assert str(pin["session_id"]) == session_id
    assert pin["line_event_id"] == "ev-1"
    assert pin["line_message_id"] == "loc-1"
    assert pin["role"] == "user"
    assert pin["type"] == "location"
    assert (pin["lat"], pin["lng"]) == PIN
    assert pin["content"] is None
    assert pin["status"] == "pending"

    buffer = await buffer_of(redis, session_id)
    assert len(buffer) == 1
    assert buffer[0]["type"] == "location"
    assert (buffer[0]["lat"], buffer[0]["lng"]) == PIN
    assert buffer[0]["reply_token"] == "rt-1"

    assert await redis.get(f"session:{session_id}:state") == "BUFFERING"
    assert await jobs(redis) == [{"kind": "chat", "session_id": session_id}]
    assert replies == []


async def test_pin_without_title_and_address_is_saved(client, db, redis, replies):
    """H9-2. ปักหมุดที่ LINE ไม่ส่ง title / address → แถว location มี lat lng · งานคุย 1 งาน"""
    await accept_pdpa(client)

    response = await post_webhook(client, location_event(*PIN, user_id="U_a", event_id="ev-1"))

    assert response.status_code == 200
    pin = await db.fetchrow("SELECT * FROM messages")
    assert pin["type"] == "location"
    assert (pin["lat"], pin["lng"]) == PIN
    assert len(await jobs(redis)) == 1


async def test_sticker_saves_keywords_as_content(client, db, redis, replies):
    """H9-3. ส่งสติกเกอร์ที่มี keywords → แถว sticker · content = keywords คั่นด้วยจุลภาค · งานคุย 1 งาน · บอทไม่ reply"""
    await accept_pdpa(client)

    response = await post_webhook(
        client,
        sticker_event(STICKER_KEYWORDS, user_id="U_a", reply_token="rt-1", event_id="ev-1", message_id="stk-1"),
    )

    assert response.status_code == 200

    sessions = await open_sessions(db)
    assert len(sessions) == 1
    session_id = str(sessions[0]["session_id"])

    sticker = await db.fetchrow("SELECT * FROM messages")
    assert sticker["type"] == "sticker"
    assert sticker["line_message_id"] == "stk-1"
    assert sticker["role"] == "user"
    assert sticker["content"] == "cony, sally, Staring, hi, whatsup, line, howdy, HEY, Peeking, wave, peek, Hello, yo, greetings"
    assert (sticker["lat"], sticker["lng"]) == (None, None)
    assert sticker["status"] == "pending"

    buffer = await buffer_of(redis, session_id)
    assert len(buffer) == 1
    assert buffer[0]["type"] == "sticker"
    assert buffer[0]["content"] == sticker["content"]
    assert buffer[0]["reply_token"] == "rt-1"

    assert await redis.get(f"session:{session_id}:state") == "BUFFERING"
    assert await jobs(redis) == [{"kind": "chat", "session_id": session_id}]
    assert replies == []


async def test_sticker_without_keywords_has_no_content(client, db, redis, replies):
    """H9-4. สติกเกอร์ที่ LINE ไม่ส่ง keywords → แถว sticker · content ว่าง · งานคุย 1 งาน"""
    await accept_pdpa(client)

    response = await post_webhook(client, sticker_event(user_id="U_a", event_id="ev-1", resource_type="STATIC"))

    assert response.status_code == 200
    sticker = await db.fetchrow("SELECT * FROM messages")
    assert sticker["type"] == "sticker"
    assert sticker["content"] is None
    assert len(await jobs(redis)) == 1


async def test_message_sticker_keeps_keywords_only(client, db, redis, replies):
    """H9-5. สติกเกอร์แบบพิมพ์ข้อความได้ (text + keywords) → content = keywords อย่างเดียว ไม่มี text"""
    await accept_pdpa(client)

    await post_webhook(
        client,
        sticker_event(
            MESSAGE_STICKER_KEYWORDS, MESSAGE_STICKER_TEXT, user_id="U_a", event_id="ev-1", resource_type="MESSAGE"
        ),
    )

    sticker = await db.fetchrow("SELECT * FROM messages")
    assert sticker["type"] == "sticker"
    assert sticker["content"] == "Anticipation, Sparkle, Straight face, Staring, Thinking"


async def test_text_pin_sticker_join_same_session_in_order(client, db, redis, replies):
    """H9-6. พิมพ์ → ปักหมุด → ส่งสติกเกอร์ (BUFFERING) → ใบเดียว · 3 แถว · buffer เรียงตามที่ส่ง · งานคุยยัง 1 งาน"""
    await accept_pdpa(client)

    await post_webhook(client, text_event("น้ำท่วมหน้าบ้าน", user_id="U_a", reply_token="rt-1", event_id="ev-1", message_id="m-1"))
    await post_webhook(client, location_event(*PIN, user_id="U_a", reply_token="rt-2", event_id="ev-2", message_id="loc-2"))
    await post_webhook(
        client, sticker_event(STICKER_KEYWORDS, user_id="U_a", reply_token="rt-3", event_id="ev-3", message_id="stk-3")
    )

    sessions = await open_sessions(db)
    assert len(sessions) == 1
    session_id = str(sessions[0]["session_id"])

    assert await db.fetchval("SELECT count(*) FROM messages") == 3
    buffer = await buffer_of(redis, session_id)
    assert [item["type"] for item in buffer] == ["text", "location", "sticker"]
    assert [item["reply_token"] for item in buffer] == ["rt-1", "rt-2", "rt-3"]
    assert await jobs(redis) == [{"kind": "chat", "session_id": session_id}]
    assert replies == []


@pytest.mark.parametrize(
    "event",
    [location_event(*PIN, user_id="U_a", reply_token="rt-7"), sticker_event(STICKER_KEYWORDS, user_id="U_a", reply_token="rt-7")],
    ids=["pin", "sticker"],
)
async def test_pin_or_sticker_before_accept_replies_card_and_stores_nothing(client, db, redis, replies, event):
    """H9-7. ปักหมุด / ส่งสติกเกอร์ก่อนกดยอมรับ → ได้การ์ดอีกครั้ง · ไม่เก็บ · ไม่มี User · ไม่มีงาน (LC1)"""
    response = await post_webhook(client, event)

    assert response.status_code == 200
    assert len(replies) == 1
    assert replies[0][0] == "rt-7"
    assert is_pdpa_card(replies[0])
    assert await db.fetchval("SELECT count(*) FROM users") == 0
    assert await db.fetchval("SELECT count(*) FROM messages") == 0
    assert await jobs(redis) == []


async def test_audio_is_not_stored_and_gets_no_reply(client, db, redis, replies):
    """H9-8. ส่งเสียง (ชนิดที่ยังไม่รับ) → 200 · ไม่เก็บ · ไม่มีงาน · บอทไม่ reply"""
    await accept_pdpa(client)

    response = await post_webhook(client, audio_event(user_id="U_a", event_id="ev-1"))

    assert response.status_code == 200
    assert await db.fetchval("SELECT count(*) FROM messages") == 0
    assert await jobs(redis) == []
    assert replies == []
