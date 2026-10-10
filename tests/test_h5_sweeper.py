"""H5 Sweeper ปิดใบ — S7 · spec ใน #153 · แบบ docs/designs/09-modules/h5-sweeper.puml"""

import json

from tests.line_webhook import post_webhook, postback_event, text_event

SESSION_KEYS = ("buffer", "last_message_at", "state", "history")


async def talked_and_answered(client, db, redis, user_id="U_a", event_id="ev-1"):
    """ผู้แจ้งยอมรับ PDPA แล้วคุยจบหนึ่งรอบ → ใบ open · state IDLE · history 2 รายการ · คืน session_id

    จำลอง worker ตอบเสร็จ (H4): หยิบงาน · ล้าง buffer · state กลับเป็น IDLE · ต่อ history
    """
    await post_webhook(client, postback_event("pdpa_accept", user_id=user_id, event_id=f"{event_id}-accept"))
    await post_webhook(client, text_event("น้ำท่วมหน้าบ้าน", user_id=user_id, event_id=event_id, message_id=event_id))
    session_id = await db.fetchval(
        """
        SELECT s.session_id FROM sessions s JOIN users u USING (user_id)
        WHERE u.line_user_id = $1 AND s.status = 'open'
        """,
        user_id,
    )
    await redis.delete("jobs", f"session:{session_id}:buffer", f"session:{session_id}:state")
    await redis.rpush(
        f"session:{session_id}:history",
        json.dumps({"role": "user", "type": "text", "content": "น้ำท่วมหน้าบ้าน"}),
        json.dumps({"role": "assistant", "type": "text", "content": "น้ำสูงแค่ไหนครับ"}),
    )
    return session_id


async def silent_for(db, session_id, minutes):
    """ย้อน last_message_at ใน PSQL — sweeper ดูเวลานี้"""
    await db.execute(
        "UPDATE sessions SET last_message_at = now() - make_interval(mins => $2) WHERE session_id = $1",
        session_id,
        minutes,
    )


async def status_of(db, session_id):
    return await db.fetchval("SELECT status FROM sessions WHERE session_id = $1", session_id)


async def jobs(redis):
    return [json.loads(item) for item in await redis.lrange("jobs", 0, -1)]


async def sweep():
    from app.workers import sweeper

    await sweeper.sweep()


async def finish_closing(db, session_id):
    """เรียกขั้นปิดของ sweeper กับใบที่เป็น CLOSING แล้ว"""
    from app.models.session import Session
    from app.workers import sweeper

    user_id = await db.fetchval("SELECT user_id FROM sessions WHERE session_id = $1", session_id)
    await sweeper.finish_closing(Session(session_id=session_id, user_id=user_id))


async def assert_skipped(db, redis, session_id, state):
    """sweeper ข้ามใบนี้: ยัง open · ไม่มีงาน · state ไม่เปลี่ยน"""
    assert await status_of(db, session_id) == "open"
    assert await jobs(redis) == []
    assert await redis.get(f"session:{session_id}:state") == state


# 1. กวาดแล้วปิด


async def test_sweep_closes_silent_idle_session(client, db, redis):
    """1.1 ใบเงียบ 11 นาที · IDLE → closed · มี closed_at · งานวิเคราะห์ 1 งาน · key ของใบใน Redis หายหมด"""
    session_id = await talked_and_answered(client, db, redis)
    await silent_for(db, session_id, 11)

    await sweep()

    row = await db.fetchrow("SELECT status, closed_at FROM sessions WHERE session_id = $1", session_id)
    assert row["status"] == "closed"
    assert row["closed_at"] is not None
    assert await jobs(redis) == [{"kind": "analyse", "session_id": str(session_id)}]
    assert await redis.exists(*[f"session:{session_id}:{name}" for name in SESSION_KEYS]) == 0


async def test_message_after_close_opens_new_session(client, db, redis):
    """1.2 ปิดใบแล้วผู้แจ้งพิมพ์มาใหม่ → ใบใหม่ · ใบเดิมยัง closed · มีงานคุยของใบใหม่"""
    old = await talked_and_answered(client, db, redis)
    await silent_for(db, old, 11)
    await sweep()

    await post_webhook(client, text_event("ตอนนี้น้ำลดแล้ว", user_id="U_a", event_id="ev-2", message_id="m-2"))

    new = await db.fetchval("SELECT session_id FROM sessions WHERE status = 'open'")
    assert new is not None
    assert new != old
    assert await status_of(db, old) == "closed"
    assert await jobs(redis) == [
        {"kind": "analyse", "session_id": str(old)},
        {"kind": "chat", "session_id": str(new)},
    ]


# 2. กวาดแล้วไม่ปิด


async def test_sweep_keeps_session_not_silent_long_enough(client, db, redis):
    """2.1 ใบเงียบแค่ 5 นาที · IDLE → ยัง open · ไม่มีงาน · history ยังอยู่"""
    session_id = await talked_and_answered(client, db, redis)
    await silent_for(db, session_id, 5)

    await sweep()

    await assert_skipped(db, redis, session_id, None)
    assert await redis.llen(f"session:{session_id}:history") == 2


async def test_sweep_skips_buffering_session(client, db, redis):
    """2.2 ใบเงียบ 11 นาที · BUFFERING (รอเงียบอยู่) → ข้าม · state ยังเป็น BUFFERING"""
    session_id = await talked_and_answered(client, db, redis)
    await redis.set(f"session:{session_id}:state", "BUFFERING")
    await silent_for(db, session_id, 11)

    await sweep()

    await assert_skipped(db, redis, session_id, "BUFFERING")


async def test_sweep_skips_processing_session(client, db, redis):
    """2.3 ใบเงียบ 11 นาที · PROCESSING (worker กำลังตอบ) → ข้าม · state ยังเป็น PROCESSING"""
    session_id = await talked_and_answered(client, db, redis)
    await redis.set(f"session:{session_id}:state", "PROCESSING")
    await silent_for(db, session_id, 11)

    await sweep()

    await assert_skipped(db, redis, session_id, "PROCESSING")


async def test_sweep_skips_session_already_closing(client, db, redis):
    """2.4 ใบเงียบ 11 นาที · CLOSING อยู่แล้ว (มีคนกำลังปิด) → ข้าม · ไม่มีงานซ้ำ · state ยังเป็น CLOSING"""
    session_id = await talked_and_answered(client, db, redis)
    await redis.set(f"session:{session_id}:state", "CLOSING")
    await silent_for(db, session_id, 11)

    await sweep()

    await assert_skipped(db, redis, session_id, "CLOSING")


async def test_message_during_closing_hands_session_back(client, db, redis):
    """2.5 ปิดไม่สำเร็จ มีข้อความแทรกตอน CLOSING · buffer มีของ → คืนใบ · ยัง open · BUFFERING · งานคุย 1 งาน"""
    session_id = await talked_and_answered(client, db, redis)
    await silent_for(db, session_id, 11)
    await redis.set(f"session:{session_id}:state", "CLOSING")  # sweeper ได้ใบนี้ไปปิดแล้ว

    await post_webhook(client, text_event("ตอนนี้น้ำลดแล้ว", user_id="U_a", event_id="ev-2", message_id="m-2"))
    assert await jobs(redis) == []  # controller ใส่งานไม่ได้ เพราะ state ไม่ว่าง

    await finish_closing(db, session_id)

    assert await status_of(db, session_id) == "open"
    assert await redis.get(f"session:{session_id}:state") == "BUFFERING"
    assert await jobs(redis) == [{"kind": "chat", "session_id": str(session_id)}]


async def test_closing_interrupted_with_empty_buffer_goes_idle(client, db, redis):
    """2.6 ปิดไม่สำเร็จ มีข้อความแทรกตอน CLOSING · buffer ยังว่าง → คืนใบ · ยัง open · IDLE · ไม่มีงาน

    จังหวะ: controller ขยับ last_message_at ใน PSQL แล้ว แต่ยังไม่ทันต่อ buffer
    """
    session_id = await talked_and_answered(client, db, redis)
    await redis.set(f"session:{session_id}:state", "CLOSING")
    await silent_for(db, session_id, 0)  # last_message_at = ตอนนี้ · buffer ยังว่าง

    await finish_closing(db, session_id)

    assert await status_of(db, session_id) == "open"
    assert not await redis.exists(f"session:{session_id}:state")
    assert await jobs(redis) == []
    assert await redis.llen(f"session:{session_id}:history") == 2


# 3. กวาดแล้วเจอทั้งสองแบบ


async def test_sweep_closes_only_the_silent_one(client, db, redis):
    """3.1 สองคน · IDLE ทั้งคู่: คนหนึ่งเงียบ 11 นาที อีกคนเพิ่งพิมพ์ → ปิดแค่ใบที่เงียบ · งานวิเคราะห์ 1 งาน"""
    silent = await talked_and_answered(client, db, redis, user_id="U_a", event_id="ev-a")
    active = await talked_and_answered(client, db, redis, user_id="U_b", event_id="ev-b")
    await silent_for(db, silent, 11)

    await sweep()

    assert await status_of(db, silent) == "closed"
    assert await status_of(db, active) == "open"
    assert await jobs(redis) == [{"kind": "analyse", "session_id": str(silent)}]


async def test_sweep_closes_only_the_idle_one(client, db, redis):
    """3.2 สองคน เงียบ 11 นาทีทั้งคู่: คนหนึ่ง IDLE อีกคน BUFFERING → ปิดแค่ใบที่ IDLE · งานวิเคราะห์ 1 งาน"""
    idle = await talked_and_answered(client, db, redis, user_id="U_a", event_id="ev-a")
    talking = await talked_and_answered(client, db, redis, user_id="U_b", event_id="ev-b")
    await redis.set(f"session:{talking}:state", "BUFFERING")
    await silent_for(db, idle, 11)
    await silent_for(db, talking, 11)

    await sweep()

    assert await status_of(db, idle) == "closed"
    assert await status_of(db, talking) == "open"
    assert await redis.get(f"session:{talking}:state") == "BUFFERING"
    assert await jobs(redis) == [{"kind": "analyse", "session_id": str(idle)}]


# 4. กวาดแล้วกวาดอีกรอบ


async def test_sweeping_twice_queues_analyse_once(client, db, redis):
    """4.1 รอบแรกปิดแล้ว → รอบสองไม่มีงานเพิ่ม (ใบปิดแล้วไม่ถูกปิดซ้ำ)"""
    session_id = await talked_and_answered(client, db, redis)
    await silent_for(db, session_id, 11)

    await sweep()
    await sweep()

    assert await jobs(redis) == [{"kind": "analyse", "session_id": str(session_id)}]


async def test_second_sweep_closes_after_talk_ends(client, db, redis):
    """4.2 รอบแรกข้ามเพราะ BUFFERING · คุยจบกลับเป็น IDLE → รอบสองปิดได้ · งานวิเคราะห์ 1 งาน"""
    session_id = await talked_and_answered(client, db, redis)
    await redis.set(f"session:{session_id}:state", "BUFFERING")
    await silent_for(db, session_id, 11)

    await sweep()
    assert await status_of(db, session_id) == "open"

    await redis.delete(f"session:{session_id}:state")  # จำลอง worker ตอบเสร็จ → IDLE
    await sweep()

    assert await status_of(db, session_id) == "closed"
    assert await jobs(redis) == [{"kind": "analyse", "session_id": str(session_id)}]


# 5. ไม่มี session ให้กวาด


async def test_sweep_with_no_sessions_does_nothing(client, db, redis):
    """5. ยังไม่มีใบเลย → ไม่พัง · ไม่มีงาน"""
    await sweep()

    assert await db.fetchval("SELECT count(*) FROM sessions") == 0
    assert await jobs(redis) == []
