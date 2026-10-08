"""H1 ผู้แจ้งยอมรับ PDPA — S1 · spec ใน #149 · แบบ docs/designs/09-modules/h1-pdpa.puml"""

from tests.line_webhook import follow_event, post_webhook, postback_event, sign, text_event, webhook_body


async def count_users(db):
    return await db.fetchval("SELECT count(*) FROM users")


def is_pdpa_card(reply):
    from app.services import pdpa

    _, messages = reply
    return messages == [pdpa.card()]


async def test_follow_replies_pdpa_card_and_stores_nothing(client, db, replies):
    """1. คนเพิ่มเพื่อนบอทครั้งแรก → ได้การ์ด PDPA · ยังไม่เก็บอะไรของเขา"""
    response = await post_webhook(client, follow_event(reply_token="rt-1"))

    assert response.status_code == 200
    assert len(replies) == 1
    assert replies[0][0] == "rt-1"
    assert is_pdpa_card(replies[0])
    assert await count_users(db) == 0


async def test_accept_creates_user_without_reply(client, db, replies):
    """2. กดยอมรับ → มี User พร้อมเวลาที่ยอมรับ · บอทไม่ตอบ"""
    response = await post_webhook(client, postback_event("pdpa_accept", user_id="U_a"))

    assert response.status_code == 200
    row = await db.fetchrow("SELECT line_user_id, pdpa_accepted_at FROM users")
    assert row["line_user_id"] == "U_a"
    assert row["pdpa_accepted_at"] is not None
    assert replies == []


async def test_accept_twice_keeps_first_accepted_at(client, db, replies):
    """3. กดยอมรับซ้ำ → ยังมี User เดียว · เวลายอมรับเท่าครั้งแรก"""
    await post_webhook(client, postback_event("pdpa_accept", user_id="U_a", event_id="ev-1"))
    first = await db.fetchval("SELECT pdpa_accepted_at FROM users")

    await post_webhook(client, postback_event("pdpa_accept", user_id="U_a", event_id="ev-2"))

    assert await count_users(db) == 1
    assert await db.fetchval("SELECT pdpa_accepted_at FROM users") == first


async def test_message_before_accept_replies_card_and_stores_nothing(client, db, replies):
    """4. พิมพ์มาก่อนกดยอมรับ → ได้การ์ดอีกครั้ง · ไม่เก็บข้อความ · ไม่มี User (LC1)"""
    response = await post_webhook(client, text_event("น้ำท่วมหน้าบ้าน", reply_token="rt-4"))

    assert response.status_code == 200
    assert len(replies) == 1
    assert replies[0][0] == "rt-4"
    assert is_pdpa_card(replies[0])
    assert await count_users(db) == 0
    assert await db.fetchval("SELECT count(*) FROM messages") == 0


async def test_message_after_accept_gets_no_card(client, db, replies):
    """5. พิมพ์มาหลังกดยอมรับ → ไม่ได้การ์ด (ที่เหลือเป็นของ H2)"""
    await post_webhook(client, postback_event("pdpa_accept", user_id="U_a"))

    await post_webhook(client, text_event("น้ำท่วมหน้าบ้าน", user_id="U_a"))

    assert not any(is_pdpa_card(reply) for reply in replies)


async def test_other_postback_does_nothing(client, db, replies):
    """6. กดปุ่มอื่นที่ไม่ใช่ปุ่มยอมรับ → ไม่สร้าง User · ไม่ตอบ"""
    response = await post_webhook(client, postback_event("something_else"))

    assert response.status_code == 200
    assert await count_users(db) == 0
    assert replies == []


async def test_bad_signature_is_rejected(client, db, replies):
    """7. webhook ปลอม (ลายเซ็นไม่ตรง) → 400 · ไม่ตอบ · ไม่เขียน DB"""
    body = webhook_body(postback_event("pdpa_accept"))

    response = await post_webhook(
        client, postback_event("pdpa_accept"), signature=sign(body, secret="wrong-secret")
    )

    assert response.status_code == 400
    assert replies == []
    assert await count_users(db) == 0


async def test_every_event_in_one_webhook_is_handled(client, db, replies):
    """8. webhook เดียวมีเพิ่มเพื่อน + พิมพ์ข้อความ (ยังไม่ยอมรับ) → ทำครบทั้งสอง · ได้การ์ด 2 ครั้ง"""
    response = await post_webhook(
        client,
        follow_event(reply_token="rt-a", event_id="ev-a"),
        text_event("สวัสดี", reply_token="rt-b", event_id="ev-b"),
    )

    assert response.status_code == 200
    assert [token for token, _ in replies] == ["rt-a", "rt-b"]
    assert all(is_pdpa_card(reply) for reply in replies)
