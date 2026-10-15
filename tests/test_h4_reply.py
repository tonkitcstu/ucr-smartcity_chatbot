"""H4 Worker ตอบผู้แจ้ง — S2 S3 · spec ใน #152 · แบบ docs/designs/09-modules/h4-reply.puml"""

import asyncio
import json
from pathlib import Path

import pytest

from tests.line_webhook import (
    PIN,
    PIN_ADDRESS,
    PIN_TITLE,
    STICKER_KEYWORDS,
    image_event,
    location_event,
    post_webhook,
    postback_event,
    sticker_event,
    text_event,
)

ANSWER = "น้ำสูงแค่ไหนครับ"
# คำตอบดิบของ AI ตามรูปแบบ ChatAnswer (H10 H11) — ข้อความ ANSWER ข้อความเดียว ไม่มีปุ่ม
RAW_ANSWER = json.dumps({"texts": [ANSWER], "buttons": []}, ensure_ascii=False)
CHAT_PROMPT = "คุณคือน้องเมือง"
CHAT_MODEL = "test-chat-model"
IMAGE_BYTES = b"fake-jpg"


@pytest.fixture
async def ai_config(db):
    """ai_configs 1 ชุดเป็นแถวที่ใช้ (#242) — ตัวคุยกับตัววิเคราะห์ใช้ model / prompt เดียวกัน"""
    model_id = await db.fetchval(
        "INSERT INTO models (provider, name) VALUES ('test', $1) RETURNING model_id", CHAT_MODEL
    )
    prompt_id = await db.fetchval("INSERT INTO prompts (prompt) VALUES ($1) RETURNING prompt_id", CHAT_PROMPT)
    await db.execute("UPDATE ai_configs SET is_active = false WHERE is_active")
    return await db.fetchval(
        """
        INSERT INTO ai_configs (chat_model_id, chat_prompt_id, analyzer_model_id, analyzer_prompt_id, is_active)
        VALUES ($1, $2, $1, $2, true) RETURNING ai_config_id
        """,
        model_id,
        prompt_id,
    )


@pytest.fixture
def ai_answers():
    """คำตอบดิบที่ AI ปลอมคืนตามลำดับ · ไม่ใส่ หรือหมดแล้ว → RAW_ANSWER"""
    return []


@pytest.fixture
def ai_schemas():
    """รูปแบบคำตอบที่ตัวคุยส่งให้ AI ปลอมแต่ละครั้ง"""
    return []


@pytest.fixture
def ai_calls(monkeypatch, ai_answers, ai_schemas):
    """แทน clients/ai.chat — คืนคำตอบดิบจาก ai_answers · จดว่าได้ model กับ messages อะไร"""
    from app.clients import ai
    from app.models.ai import AiReply

    calls = []

    async def fake_chat(model, messages, schema):
        calls.append((model, messages))
        ai_schemas.append(schema)
        return AiReply(text=ai_answers.pop(0) if ai_answers else RAW_ANSWER, input_tokens=10, output_tokens=5)

    monkeypatch.setattr(ai, "chat", fake_chat)
    return calls


@pytest.fixture
def loadings(monkeypatch):
    """แทน clients/line.show_loading — จดว่าเปิดให้ใคร"""
    from app.clients import line

    calls = []

    async def fake_show_loading(line_user_id):
        calls.append(line_user_id)

    monkeypatch.setattr(line, "show_loading", fake_show_loading)
    return calls


@pytest.fixture
def downloads(monkeypatch):
    """แทน clients/line.download_message_content — คืน IMAGE_BYTES · จดว่าขอ id ไหน"""
    from app.clients import line

    calls = []

    async def fake_download(line_message_id):
        calls.append(line_message_id)
        return IMAGE_BYTES

    monkeypatch.setattr(line, "download_message_content", fake_download)
    return calls


@pytest.fixture
def outside(ai_config, ai_calls, loadings, downloads, replies):
    """ของนอกบ้านปลอมครบชุด"""


async def accept_pdpa(client, user_id="U_a"):
    await post_webhook(client, postback_event("pdpa_accept", user_id=user_id, event_id="ev-accept"))


async def pop_job(redis):
    from app.models.job import Job

    return Job.model_validate_json(await redis.lpop("jobs"))


async def run_next_job(redis):
    """ทำหน้าที่แทนตัววนของ worker: หยิบงาน 1 ใบ แล้ว run_chat จนจบ"""
    from app.workers import worker

    await worker.run_chat(await pop_job(redis))


async def history_of(redis, session_id):
    return [json.loads(item) for item in await redis.lrange(f"session:{session_id}:history", 0, -1)]


def sent_to_ai(call):
    _, messages = call
    return [(m.role, m.type, m.content) for m in messages]


async def test_text_and_image_get_one_reply_with_latest_token(
    client, db, redis, outside, ai_config, ai_calls, loadings, downloads, replies
):
    """1. พิมพ์ "น้ำท่วมหน้าบ้าน" แล้วส่งรูป → เก็บรูป · AI ครั้งเดียวได้ครบ · reply ด้วย token ของรูป · ตอบแล้ว · IDLE"""
    await accept_pdpa(client)
    await post_webhook(client, text_event("น้ำท่วมหน้าบ้าน", user_id="U_a", reply_token="rt-1", event_id="ev-1", message_id="m-1"))
    await post_webhook(client, image_event(user_id="U_a", reply_token="rt-2", event_id="ev-2", message_id="img-2"))
    [session] = await db.fetch("SELECT session_id FROM sessions WHERE status = 'open'")
    session_id = session["session_id"]

    await run_next_job(redis)

    assert loadings == ["U_a"]

    assert downloads == ["img-2"]
    attachment = await db.fetchrow(
        "SELECT a.* FROM attachments a JOIN messages m USING (message_id) WHERE m.line_message_id = 'img-2'"
    )
    assert attachment["type"] == "image"
    assert Path(attachment["file_path"]).read_bytes() == IMAGE_BYTES

    assert len(ai_calls) == 1
    assert ai_calls[0][0] == CHAT_MODEL
    assert sent_to_ai(ai_calls[0]) == [
        ("system", "text", CHAT_PROMPT),
        ("user", "text", "น้ำท่วมหน้าบ้าน"),
        ("user", "image", attachment["file_path"]),
    ]

    ai_call = await db.fetchrow("SELECT * FROM ai_calls")
    assert ai_call["session_id"] == session_id
    assert ai_call["ai_config_id"] == ai_config
    assert ai_call["kind"] == "communicator"
    assert ai_call["status"] == "ok"
    assert ai_call["response"] == RAW_ANSWER

    assert len(replies) == 1
    reply_token, messages = replies[0]
    assert reply_token == "rt-2"
    assert [m.text for m in messages] == [ANSWER]

    reporter_rows = await db.fetch("SELECT status FROM messages WHERE role = 'user'")
    assert [row["status"] for row in reporter_rows] == ["answered", "answered"]
    bot = await db.fetchrow("SELECT * FROM messages WHERE role = 'assistant'")
    assert bot["session_id"] == session_id
    assert bot["content"] == ANSWER

    assert await redis.llen(f"session:{session_id}:buffer") == 0
    assert not await redis.exists(f"session:{session_id}:state")
    assert await history_of(redis, session_id) == [
        {"role": "user", "type": "text", "content": "น้ำท่วมหน้าบ้าน"},
        {"role": "user", "type": "image", "content": attachment["file_path"]},
        {"role": "assistant", "type": "text", "content": ANSWER},
    ]


async def test_text_only_downloads_nothing(client, db, redis, outside, ai_calls, downloads, replies):
    """2. พิมพ์อย่างเดียว ไม่มีรูป → ไม่ดาวน์โหลด · ไม่มี attachment · AI ได้ system + ข้อความ"""
    await accept_pdpa(client)
    await post_webhook(client, text_event("ถนนหน้าบ้านเป็นหลุม", user_id="U_a", reply_token="rt-1", event_id="ev-1"))

    await run_next_job(redis)

    assert downloads == []
    assert await db.fetchval("SELECT count(*) FROM attachments") == 0
    assert sent_to_ai(ai_calls[0]) == [
        ("system", "text", CHAT_PROMPT),
        ("user", "text", "ถนนหน้าบ้านเป็นหลุม"),
    ]
    assert [token for token, _ in replies] == ["rt-1"]


async def test_message_during_silence_joins_same_ai_call(client, db, redis, outside, ai_calls, replies):
    """3. ข้อความมาระหว่างรอเงียบ → รอต่อจนเงียบหลังข้อความล่าสุด · AI ครั้งเดียวได้ทั้งสอง · reply ด้วย token ล่าสุด"""
    from app.workers import worker

    await accept_pdpa(client)
    await post_webhook(client, text_event("น้ำท่วม", user_id="U_a", reply_token="rt-1", event_id="ev-1", message_id="m-1"))
    job = await pop_job(redis)

    task = asyncio.create_task(worker.run_chat(job))
    await asyncio.sleep(0.1)  # ยังไม่ครบ SILENCE_SECONDS (0.3)
    assert ai_calls == []
    await post_webhook(client, text_event("หน้าบ้าน", user_id="U_a", reply_token="rt-2", event_id="ev-2", message_id="m-2"))
    await task

    assert len(ai_calls) == 1
    assert sent_to_ai(ai_calls[0]) == [
        ("system", "text", CHAT_PROMPT),
        ("user", "text", "น้ำท่วม"),
        ("user", "text", "หน้าบ้าน"),
    ]
    assert [token for token, _ in replies] == ["rt-2"]
    assert await redis.llen("jobs") == 0


async def test_next_round_sends_history_to_ai(client, db, redis, outside, ai_calls, replies):
    """4. คุยรอบที่ 2 ในใบเดิม → AI ได้ system + ประวัติรอบแรก + ข้อความใหม่ · ประวัติยาวขึ้น"""
    await accept_pdpa(client)
    await post_webhook(client, text_event("น้ำท่วมหน้าบ้าน", user_id="U_a", reply_token="rt-1", event_id="ev-1", message_id="m-1"))
    await run_next_job(redis)

    await post_webhook(client, text_event("สูงประมาณเข่า", user_id="U_a", reply_token="rt-2", event_id="ev-2", message_id="m-2"))
    await run_next_job(redis)

    assert len(ai_calls) == 2
    assert sent_to_ai(ai_calls[1]) == [
        ("system", "text", CHAT_PROMPT),
        ("user", "text", "น้ำท่วมหน้าบ้าน"),
        ("assistant", "text", ANSWER),
        ("user", "text", "สูงประมาณเข่า"),
    ]
    assert [token for token, _ in replies] == ["rt-1", "rt-2"]

    [session] = await db.fetch("SELECT session_id FROM sessions WHERE status = 'open'")
    assert len(await history_of(redis, session["session_id"])) == 4
    assert await db.fetchval("SELECT count(*) FROM messages WHERE role = 'assistant'") == 2


async def test_chat_job_through_handle_gets_reply(client, db, redis, outside, ai_calls, replies):
    """5. งาน kind chat เข้า handle → คุยเหมือนเดิม: AI 1 ครั้ง · reply 1 ครั้ง"""
    from app.workers import worker

    await accept_pdpa(client)
    await post_webhook(client, text_event("ถนนหน้าบ้านเป็นหลุม", user_id="U_a", reply_token="rt-1", event_id="ev-1"))

    await worker.handle(await pop_job(redis))

    assert len(ai_calls) == 1
    assert [token for token, _ in replies] == ["rt-1"]


# --- H9 รับตำแหน่งและสติกเกอร์ — S4 S13 · spec ใน #219 · แบบ docs/designs/09-modules/h9-location-sticker.puml ---

PIN_NOTE = "[ระบบ: ผู้แจ้งปักหมุดตำแหน่งแล้ว]"
STICKER_NOTE = (
    "[ระบบ: ผู้แจ้งส่งสติกเกอร์ คำบรรยาย: "
    "cony, sally, Staring, hi, whatsup, line, howdy, HEY, Peeking, wave, peek, Hello, yo, greetings]"
)
BARE_STICKER_NOTE = "[ระบบ: ผู้แจ้งส่งสติกเกอร์]"


async def test_pin_alone_gets_reply_and_ai_sees_note_without_coordinates(
    client, db, redis, outside, ai_calls, downloads, replies
):
    """H9-9. ปักหมุดอย่างเดียว → AI ได้ system + ป้ายตำแหน่ง ไม่มีพิกัด · ไม่ดาวน์โหลด · reply ด้วย token ของหมุด · ตอบแล้ว · IDLE"""
    await accept_pdpa(client)
    await post_webhook(
        client,
        location_event(*PIN, user_id="U_a", reply_token="rt-1", event_id="ev-1", title=PIN_TITLE, address=PIN_ADDRESS),
    )
    [session] = await db.fetch("SELECT session_id FROM sessions WHERE status = 'open'")
    session_id = session["session_id"]

    await run_next_job(redis)

    assert len(ai_calls) == 1
    assert sent_to_ai(ai_calls[0]) == [
        ("system", "text", CHAT_PROMPT),
        ("user", "text", PIN_NOTE),
    ]

    assert downloads == []
    assert await db.fetchval("SELECT count(*) FROM attachments") == 0

    assert len(replies) == 1
    reply_token, messages = replies[0]
    assert reply_token == "rt-1"
    assert [m.text for m in messages] == [ANSWER]

    assert await db.fetchval("SELECT status FROM messages WHERE type = 'location'") == "answered"
    assert await redis.llen(f"session:{session_id}:buffer") == 0
    assert not await redis.exists(f"session:{session_id}:state")
    assert await history_of(redis, session_id) == [
        {"role": "user", "type": "text", "content": PIN_NOTE},
        {"role": "assistant", "type": "text", "content": ANSWER},
    ]


@pytest.mark.parametrize(
    ("keywords", "note"),
    [(STICKER_KEYWORDS, STICKER_NOTE), (None, BARE_STICKER_NOTE)],
    ids=["with-keywords", "no-keywords"],
)
async def test_sticker_alone_gets_reply(client, db, redis, outside, ai_calls, downloads, replies, keywords, note):
    """H9-10, H9-11. สติกเกอร์อย่างเดียว → AI ได้ system + ป้ายสติกเกอร์ (มีคำบรรยาย / เปล่า) · reply 1 ครั้ง · ตอบแล้ว"""
    await accept_pdpa(client)
    await post_webhook(client, sticker_event(keywords, user_id="U_a", reply_token="rt-1", event_id="ev-1"))

    await run_next_job(redis)

    assert len(ai_calls) == 1
    assert sent_to_ai(ai_calls[0]) == [
        ("system", "text", CHAT_PROMPT),
        ("user", "text", note),
    ]
    assert downloads == []
    assert [token for token, _ in replies] == ["rt-1"]
    assert await db.fetchval("SELECT status FROM messages WHERE type = 'sticker'") == "answered"


async def test_text_pin_sticker_image_go_to_ai_in_order(client, db, redis, outside, ai_calls, downloads, replies):
    """H9-12. พิมพ์ + ปักหมุด + สติกเกอร์ + รูป ในรอบเดียว → AI ครั้งเดียว เรียงตามที่ส่ง · ดาวน์โหลดเฉพาะรูป · reply ด้วย token ล่าสุด"""
    await accept_pdpa(client)
    await post_webhook(client, text_event("น้ำท่วมหน้าบ้าน", user_id="U_a", reply_token="rt-1", event_id="ev-1", message_id="m-1"))
    await post_webhook(client, location_event(*PIN, user_id="U_a", reply_token="rt-2", event_id="ev-2", message_id="loc-2"))
    await post_webhook(
        client, sticker_event(STICKER_KEYWORDS, user_id="U_a", reply_token="rt-3", event_id="ev-3", message_id="stk-3")
    )
    await post_webhook(client, image_event(user_id="U_a", reply_token="rt-4", event_id="ev-4", message_id="img-4"))

    await run_next_job(redis)

    assert downloads == ["img-4"]
    file_path = await db.fetchval("SELECT file_path FROM attachments")

    assert len(ai_calls) == 1
    assert sent_to_ai(ai_calls[0]) == [
        ("system", "text", CHAT_PROMPT),
        ("user", "text", "น้ำท่วมหน้าบ้าน"),
        ("user", "text", PIN_NOTE),
        ("user", "text", STICKER_NOTE),
        ("user", "image", file_path),
    ]
    assert [token for token, _ in replies] == ["rt-4"]
    assert await db.fetchval("SELECT count(*) FROM messages WHERE role = 'user' AND status = 'answered'") == 4


# --- H10 ตัวคุยเลือกปุ่มใต้ข้อความ — S3 S4 · spec ใน #226 · แบบ docs/designs/09-modules/h10-quick-reply.puml ---

ASK_PIN = "ตรงนี้เกิดขึ้นแถวไหนเหรอคะ พอจะแชร์ตำแหน่งให้เมืองหน่อยได้ไหมคะ"
ASK_PHOTO = "ขอบคุณค่ะ ส่งรูปมาให้เมืองดูได้เลยนะคะ"
# คำบนปุ่มที่ AI แต่งตอนลองยิงจริง 2026-10-13
PIN_BUTTON = ("location", "แชร์ตำแหน่ง")
CAMERA_BUTTON = ("camera", "ถ่ายรูป")
ALBUM_BUTTON = ("camera_roll", "เลือกจากอัลบั้ม")
# ตาเห็น 32 ตัวอักษร — สระบน สระล่าง วรรณยุกต์ ไม่นับ (H13)
LONG_LABEL = "กดตรงนี้เพื่อแชร์ตำแหน่งที่เกิดเรื่องให้เมือง"
# 20 ตัวแรกที่ตาเห็นของ LONG_LABEL · สระและวรรณยุกต์ของแต่ละตัวยังอยู่
LONG_LABEL_CUT = "กดตรงนี้เพื่อแชร์ตำแหน่งที่เ"


def raw_answer(texts, *buttons):
    """คำตอบดิบของ AI ตามรูปแบบ ChatAnswer · texts = ข้อความเดียว (str) หรือหลายข้อความ (list) · ปุ่ม = (type, label)"""
    return json.dumps(
        {
            "texts": [texts] if isinstance(texts, str) else texts,
            "buttons": [{"type": kind, "label": label} for kind, label in buttons],
        },
        ensure_ascii=False,
    )


def quick_reply_of(message):
    """[(ชนิด action ของ LINE, คำบนปุ่ม)] ของข้อความที่ส่งกลับ · ไม่มี quick reply → []"""
    if message.quick_reply is None:
        return []
    return [(item.action.type, item.action.label) for item in message.quick_reply.items]


async def chat_one_round(client, redis, ai_answers, raw):
    """ผู้แจ้งพิมพ์หนึ่งข้อความ → worker ตอบด้วยคำตอบดิบ raw"""
    ai_answers.append(raw)
    await accept_pdpa(client)
    await post_webhook(client, text_event("น้ำท่วมหน้าบ้าน", user_id="U_a", reply_token="rt-1", event_id="ev-1"))
    await run_next_job(redis)


async def test_ai_button_becomes_quick_reply_and_only_text_is_kept(client, db, redis, outside, ai_answers, replies):
    """H10-1. AI ตอบพร้อมปุ่ม location → reply มี quick reply 1 ปุ่ม · messages และประวัติเก็บแค่ข้อความ · ai_calls เก็บ JSON ดิบ status ok"""
    raw = raw_answer(ASK_PIN, PIN_BUTTON)
    await chat_one_round(client, redis, ai_answers, raw)
    session_id = await db.fetchval("SELECT session_id FROM sessions WHERE status = 'open'")

    [(reply_token, [message])] = replies
    assert reply_token == "rt-1"
    assert message.text == ASK_PIN
    assert quick_reply_of(message) == [("location", "แชร์ตำแหน่ง")]

    assert await db.fetchval("SELECT content FROM messages WHERE role = 'assistant'") == ASK_PIN
    assert await history_of(redis, session_id) == [
        {"role": "user", "type": "text", "content": "น้ำท่วมหน้าบ้าน"},
        {"role": "assistant", "type": "text", "content": ASK_PIN},
    ]

    ai_call = await db.fetchrow("SELECT status, error, response FROM ai_calls")
    assert (ai_call["status"], ai_call["error"], ai_call["response"]) == ("ok", None, raw)


async def test_camera_and_album_buttons_keep_ai_order(client, db, redis, outside, ai_answers, replies):
    """H10-2. AI ตอบพร้อมปุ่ม camera กับ camera_roll → quick reply 2 ปุ่ม เรียงตามที่ AI ให้"""
    await chat_one_round(client, redis, ai_answers, raw_answer(ASK_PHOTO, CAMERA_BUTTON, ALBUM_BUTTON))

    [(_, [message])] = replies
    assert message.text == ASK_PHOTO
    assert quick_reply_of(message) == [("camera", "ถ่ายรูป"), ("cameraRoll", "เลือกจากอัลบั้ม")]


async def test_no_button_means_no_quick_reply(client, db, redis, outside, ai_answers, replies):
    """H10-3. AI ตอบไม่มีปุ่ม → reply มีข้อความ ไม่มี quick reply · status ok"""
    await chat_one_round(client, redis, ai_answers, raw_answer(ANSWER))

    [(_, [message])] = replies
    assert message.text == ANSWER
    assert message.quick_reply is None
    assert await db.fetchval("SELECT status FROM ai_calls") == "ok"


async def test_label_of_exactly_twenty_is_sent_whole(client, db, redis, outside, ai_answers, replies):
    """H10-4. คำบนปุ่มยาว 20 ตัวอักษรที่ตาเห็นพอดี (วิธีนับของ H13) → ส่งคำเดิมครบ · status ok"""
    label = LONG_LABEL_CUT
    await chat_one_round(client, redis, ai_answers, raw_answer(ASK_PIN, ("location", label)))

    [(_, [message])] = replies
    assert quick_reply_of(message) == [("location", label)]
    ai_call = await db.fetchrow("SELECT status, error FROM ai_calls")
    assert (ai_call["status"], ai_call["error"]) == ("ok", None)


async def test_long_label_is_cut_and_button_still_sent_with_warning(client, db, redis, outside, ai_answers, replies):
    """H10-5. คำบนปุ่มยาวเกิน 20 → ส่ง 20 ตัวแรกที่ตาเห็น (วิธีนับของ H13) ปุ่มและข้อความยังส่ง
    ai_calls status warning บอกชนิดปุ่ม · response ยังเป็นคำเต็ม"""
    raw = raw_answer(ASK_PIN, ("location", LONG_LABEL))
    await chat_one_round(client, redis, ai_answers, raw)

    [(_, [message])] = replies
    assert message.text == ASK_PIN
    assert quick_reply_of(message) == [("location", LONG_LABEL_CUT)]

    ai_call = await db.fetchrow("SELECT status, error, response FROM ai_calls")
    assert ai_call["status"] == "warning"
    assert "location" in ai_call["error"]
    assert ai_call["response"] == raw
    assert await db.fetchval("SELECT content FROM messages WHERE role = 'assistant'") == ASK_PIN


@pytest.mark.parametrize("blank", ["", "   "], ids=["empty", "spaces"])
async def test_blank_label_drops_that_button_only(client, db, redis, outside, ai_answers, replies, blank):
    """H10-6. ปุ่มคำว่างปนกับปุ่มที่ดี → ปุ่มคำว่างถูกตัดทิ้ง ปุ่มที่ดียังส่ง · status warning"""
    await chat_one_round(client, redis, ai_answers, raw_answer(ASK_PHOTO, ("camera", blank), ALBUM_BUTTON))

    [(_, [message])] = replies
    assert message.text == ASK_PHOTO
    assert quick_reply_of(message) == [("cameraRoll", "เลือกจากอัลบั้ม")]
    ai_call = await db.fetchrow("SELECT status, error FROM ai_calls")
    assert ai_call["status"] == "warning"
    assert "camera" in ai_call["error"]


async def test_only_button_blank_sends_text_without_quick_reply(client, db, redis, outside, ai_answers, replies):
    """H10-7. มีปุ่มเดียวและคำว่าง → reply มีข้อความ ไม่มี quick reply · status warning"""
    await chat_one_round(client, redis, ai_answers, raw_answer(ASK_PIN, ("location", "")))

    [(_, [message])] = replies
    assert message.text == ASK_PIN
    assert message.quick_reply is None
    assert await db.fetchval("SELECT status FROM ai_calls") == "warning"


async def test_more_than_thirteen_buttons_keeps_first_thirteen(client, db, redis, outside, ai_answers, replies):
    """H10-8. AI ให้ปุ่มเกิน 13 ปุ่ม → quick reply มี 13 ปุ่มแรก (LINE รับได้สูงสุด 13)"""
    buttons = [("camera", f"ถ่ายรูป {n}") for n in range(1, 15)]
    await chat_one_round(client, redis, ai_answers, raw_answer(ASK_PHOTO, *buttons))

    [(_, [message])] = replies
    assert quick_reply_of(message) == [("camera", f"ถ่ายรูป {n}") for n in range(1, 14)]


async def test_chat_ai_is_asked_for_text_and_button_types(client, db, redis, outside, ai_schemas):
    """H10-9. ตัวคุยถูกเรียกพร้อมรูปแบบคำตอบ: texts + buttons
    ชนิดปุ่มที่เลือกได้ = location, camera, camera_roll และ message (H13)"""
    await accept_pdpa(client)
    await post_webhook(client, text_event("น้ำท่วมหน้าบ้าน", user_id="U_a", reply_token="rt-1", event_id="ev-1"))
    await run_next_job(redis)

    [schema] = ai_schemas
    described = schema.model_json_schema()
    assert set(described["properties"]) == {"texts", "buttons"}
    button = described["$defs"]["QuickReplyButton"]
    assert set(button["properties"]) == {"type", "label"}
    assert button["properties"]["type"]["enum"] == ["location", "camera", "camera_roll", "message"]


async def test_next_round_shows_ai_its_own_text_without_buttons(client, db, redis, outside, ai_answers, ai_calls):
    """H10-10. คุยรอบที่ 2 หลังรอบที่มีปุ่ม → AI เห็นคำตอบรอบก่อนเป็นข้อความล้วน ไม่มี JSON ไม่มีปุ่ม"""
    await chat_one_round(client, redis, ai_answers, raw_answer(ASK_PIN, PIN_BUTTON))

    await post_webhook(client, text_event("แถวหลังวัดค่ะ", user_id="U_a", reply_token="rt-2", event_id="ev-2", message_id="m-2"))
    await run_next_job(redis)

    assert sent_to_ai(ai_calls[1]) == [
        ("system", "text", CHAT_PROMPT),
        ("user", "text", "น้ำท่วมหน้าบ้าน"),
        ("assistant", "text", ASK_PIN),
        ("user", "text", "แถวหลังวัดค่ะ"),
    ]


async def test_answer_that_is_not_the_format_is_recorded_as_error(client, db, redis, outside, ai_answers, replies):
    """H10-11. AI ตอบมาแกะเป็น ChatAnswer ไม่ได้ → ai_calls status error มีเหตุ · response = ของดิบ · ผู้แจ้งได้ข้อความสำรอง (#213)"""
    from app.workers.worker import FALLBACK_TEXT

    await chat_one_round(client, redis, ai_answers, "ขอโทษค่ะ ตอนนี้ตอบไม่ได้")

    assert [[m.text for m in messages] for _, messages in replies] == [[FALLBACK_TEXT]]

    ai_call = await db.fetchrow("SELECT kind, status, error, response FROM ai_calls")
    assert (ai_call["kind"], ai_call["status"], ai_call["response"]) == ("communicator", "error", "ขอโทษค่ะ ตอนนี้ตอบไม่ได้")
    assert ai_call["error"]


# --- H11 ตัวคุยแยกคำตอบเป็นหลายข้อความ — milestone 2.0.1 ข้อ 2 · spec ใน #233 · แบบ docs/designs/09-modules/h11-multi-message.puml ---

# คำตอบที่ AI แต่งตอนลองยิงจริง 2026-10-13 — สองข้อความ + ปุ่ม location
FEEL = "เป็นมาตั้งสามปีแล้ว แถมท่วมสูงถึงเข่าแบบนี้ หนักหนาเหมือนกันนะคะ"
ASK_WHERE = (
    "เวลาฝนตกทีนึง น้ำมักจะท่วมช่วงไหนหรือกี่โมงคะ "
    "แล้วพอจะแชร์ตำแหน่งตรงแถวหลังวัดให้ดูหน่อยได้ไหมคะ หรือพิมพ์บอกคร่าว ๆ ก็ได้ค่ะ"
)
TEXTS_MAX = 5


def numbered(count):
    """ข้อความ count ข้อความ: ข้อความที่ 1 … ข้อความที่ count"""
    return [f"ข้อความที่ {n}" for n in range(1, count + 1)]


async def bot_rows(db):
    """คำตอบของบอทใน messages เรียงแบบเดียวกับที่บทสนทนาอ่าน (created_at)"""
    rows = await db.fetch("SELECT content, status FROM messages WHERE role = 'assistant' ORDER BY created_at")
    return [(row["content"], row["status"]) for row in rows]


async def test_two_texts_go_out_in_one_reply_and_are_kept_one_by_one(client, db, redis, outside, ai_answers, replies):
    """H11-1. AI ตอบ 2 ข้อความ + ปุ่ม location → reply ครั้งเดียว 2 ข้อความตามลำดับ ปุ่มอยู่ที่ข้อความสุดท้าย
    messages และประวัติเก็บข้อความละรายการตามลำดับ · บทสนทนาที่ตัววิเคราะห์อ่านเรียงเหมือนกัน · ai_calls ok"""
    from app.services import session

    raw = raw_answer([FEEL, ASK_WHERE], PIN_BUTTON)
    await chat_one_round(client, redis, ai_answers, raw)
    session_id = await db.fetchval("SELECT session_id FROM sessions WHERE status = 'open'")

    [(reply_token, messages)] = replies
    assert reply_token == "rt-1"
    assert [m.text for m in messages] == [FEEL, ASK_WHERE]
    assert [quick_reply_of(m) for m in messages] == [[], [("location", "แชร์ตำแหน่ง")]]

    assert await bot_rows(db) == [(FEEL, "answered"), (ASK_WHERE, "answered")]
    transcript = await session.read_transcript(session_id)
    assert [(m.role, m.content) for m in transcript] == [
        ("user", "น้ำท่วมหน้าบ้าน"),
        ("assistant", FEEL),
        ("assistant", ASK_WHERE),
    ]
    assert await history_of(redis, session_id) == [
        {"role": "user", "type": "text", "content": "น้ำท่วมหน้าบ้าน"},
        {"role": "assistant", "type": "text", "content": FEEL},
        {"role": "assistant", "type": "text", "content": ASK_WHERE},
    ]

    ai_call = await db.fetchrow("SELECT status, error, response FROM ai_calls")
    assert (ai_call["status"], ai_call["error"], ai_call["response"]) == ("ok", None, raw)


async def test_five_texts_are_all_sent_with_buttons_on_the_last(client, db, redis, outside, ai_answers, replies):
    """H11-2. AI ตอบ 5 ข้อความพอดี + ปุ่ม camera กับ camera_roll → ส่งครบ 5 คำเดิม · ปุ่มอยู่ที่ข้อความที่ 5 เท่านั้น · status ok"""
    texts = numbered(TEXTS_MAX)
    await chat_one_round(client, redis, ai_answers, raw_answer(texts, CAMERA_BUTTON, ALBUM_BUTTON))

    [(_, messages)] = replies
    assert [m.text for m in messages] == texts
    assert [quick_reply_of(m) for m in messages] == [
        [], [], [], [], [("camera", "ถ่ายรูป"), ("cameraRoll", "เลือกจากอัลบั้ม")],
    ]
    assert await bot_rows(db) == [(text, "answered") for text in texts]
    ai_call = await db.fetchrow("SELECT status, error FROM ai_calls")
    assert (ai_call["status"], ai_call["error"]) == ("ok", None)


async def test_more_than_five_texts_fold_the_rest_into_the_fifth(client, db, redis, outside, ai_answers, replies):
    """H11-3. AI ตอบ 7 ข้อความ → ส่ง 5: สี่ข้อความแรกคงเดิม ข้อความที่ 5 = ข้อความที่ 5–7 ต่อกันคั่นด้วยขึ้นบรรทัดใหม่
    ai_calls status warning บอกจำนวน 7 · response ยังเป็น JSON เดิม · messages เก็บ 5 แถวตามที่ส่ง"""
    texts = numbered(7)
    sent = [*texts[:4], "ข้อความที่ 5\nข้อความที่ 6\nข้อความที่ 7"]
    raw = raw_answer(texts)
    await chat_one_round(client, redis, ai_answers, raw)

    [(_, messages)] = replies
    assert [m.text for m in messages] == sent
    assert await bot_rows(db) == [(text, "answered") for text in sent]

    ai_call = await db.fetchrow("SELECT status, error, response FROM ai_calls")
    assert ai_call["status"] == "warning"
    assert "7" in ai_call["error"]
    assert ai_call["response"] == raw


@pytest.mark.parametrize("blank", ["", "   ", "\n"], ids=["empty", "spaces", "newline"])
async def test_blank_text_is_dropped_and_the_rest_is_sent(client, db, redis, outside, ai_answers, replies, blank):
    """H11-4. ข้อความว่างปนกับข้อความที่ดี → ข้อความว่างถูกตัดทิ้ง ข้อความที่ดีส่งตามลำดับ · status warning"""
    await chat_one_round(client, redis, ai_answers, raw_answer([FEEL, blank, ASK_WHERE]))

    [(_, messages)] = replies
    assert [m.text for m in messages] == [FEEL, ASK_WHERE]
    assert await bot_rows(db) == [(FEEL, "answered"), (ASK_WHERE, "answered")]
    ai_call = await db.fetchrow("SELECT status, error FROM ai_calls")
    assert ai_call["status"] == "warning"
    assert ai_call["error"]


async def test_five_is_counted_after_blank_texts_are_dropped(client, db, redis, outside, ai_answers, replies):
    """H11-5. 5 ข้อความที่ดี + ข้อความว่าง 2 ข้อความแทรกอยู่ → ส่งครบ 5 คำเดิม ไม่ถูกรวม · status warning เพราะตัดข้อความว่าง"""
    texts = numbered(TEXTS_MAX)
    with_blanks = [texts[0], "", *texts[1:4], "  ", texts[4]]
    await chat_one_round(client, redis, ai_answers, raw_answer(with_blanks))

    [(_, messages)] = replies
    assert [m.text for m in messages] == texts
    assert await db.fetchval("SELECT status FROM ai_calls") == "warning"


@pytest.mark.parametrize("texts", [[], ["", "  "]], ids=["empty-list", "all-blank"])
async def test_no_text_left_is_recorded_as_error(client, db, redis, outside, ai_answers, replies, texts):
    """H11-6. ไม่เหลือข้อความให้ส่ง → ได้แค่ข้อความสำรอง (#213) · ไม่มีแถวของบอท · ai_calls status error มีเหตุ · response = ของดิบ"""
    from app.workers.worker import FALLBACK_TEXT

    raw = raw_answer(texts)

    await chat_one_round(client, redis, ai_answers, raw)

    assert [[m.text for m in messages] for _, messages in replies] == [[FALLBACK_TEXT]]
    assert await bot_rows(db) == []
    ai_call = await db.fetchrow("SELECT kind, status, error, response FROM ai_calls")
    assert (ai_call["kind"], ai_call["status"], ai_call["response"]) == ("communicator", "error", raw)
    assert ai_call["error"]


async def test_text_and_button_warnings_are_recorded_together(client, db, redis, outside, ai_answers, replies):
    """H11-7. AI ตอบ 6 ข้อความ และคำบนปุ่มยาวเกิน 20 → ส่ง 5 ข้อความ ปุ่มที่ตัดคำแล้วอยู่ที่ข้อความที่ 5
    ai_calls status warning แถวเดียว เหตุมีทั้งเรื่องข้อความและเรื่องปุ่ม"""
    await chat_one_round(client, redis, ai_answers, raw_answer(numbered(6), ("location", LONG_LABEL)))

    [(_, messages)] = replies
    assert len(messages) == TEXTS_MAX
    assert messages[-1].text == "ข้อความที่ 5\nข้อความที่ 6"
    assert [quick_reply_of(m) for m in messages] == [[], [], [], [], [("location", LONG_LABEL_CUT)]]

    [ai_call] = await db.fetch("SELECT status, error FROM ai_calls")
    assert ai_call["status"] == "warning"
    assert "6" in ai_call["error"]
    assert "location" in ai_call["error"]


async def test_chat_ai_is_asked_for_a_list_of_texts(client, db, redis, outside, ai_schemas):
    """H11-8. รูปแบบคำตอบที่ส่งให้ AI: texts เป็นรายการของ string"""
    await accept_pdpa(client)
    await post_webhook(client, text_event("น้ำท่วมหน้าบ้าน", user_id="U_a", reply_token="rt-1", event_id="ev-1"))
    await run_next_job(redis)

    [schema] = ai_schemas
    texts = schema.model_json_schema()["properties"]["texts"]
    assert texts["type"] == "array"
    assert texts["items"] == {"type": "string"}


async def test_next_round_shows_ai_each_of_its_texts(client, db, redis, outside, ai_answers, ai_calls):
    """H11-9. คุยรอบที่ 2 หลังรอบที่ตอบ 2 ข้อความ → AI เห็นคำตอบรอบก่อนเป็นข้อความฝั่ง assistant 2 รายการติดกัน ข้อความล้วน"""
    await chat_one_round(client, redis, ai_answers, raw_answer([FEEL, ASK_WHERE], PIN_BUTTON))

    await post_webhook(client, text_event("แถวหลังวัดค่ะ", user_id="U_a", reply_token="rt-2", event_id="ev-2", message_id="m-2"))
    await run_next_job(redis)

    assert sent_to_ai(ai_calls[1]) == [
        ("system", "text", CHAT_PROMPT),
        ("user", "text", "น้ำท่วมหน้าบ้าน"),
        ("assistant", "text", FEEL),
        ("assistant", "text", ASK_WHERE),
        ("user", "text", "แถวหลังวัดค่ะ"),
    ]


# --- H13 ตัวคุยยื่นปุ่มคำตอบที่แต่งเอง — milestone 2.0.1 ข้อ 1 · spec ใน #237 · แบบ docs/designs/09-modules/h13-answer-buttons.puml ---

# คำตอบที่ AI แต่งตอนลองยิงจริง 2026-10-13 — คำถาม + ปุ่มคำตอบ 2 ปุ่ม
ASK_WHEN = "ขอบคุณสำหรับตำแหน่งนะคะ แล้วบ้านร้อนแบบนี้ เป็นช่วงบ่ายหรือทั้งวันเลยคะ"
AFTERNOON_BUTTON = ("message", "เฉพาะช่วงบ่ายค่ะ")
# ตาเห็น 16 ตัวอักษร · len() นับได้ 21 เพราะนับไม้โท ไม้เอก ไม้หันอากาศด้วย
ALL_DAY_BUTTON = ("message", "ร้อนตลอดทั้งวันเลยค่ะ")
# ตาเห็น 27 ตัวอักษร
LONG_ANSWER = "ร้อนตั้งแต่สายไปจนถึงค่ำทุกวันเลยค่ะ"
# 20 ตัวแรกที่ตาเห็นของ LONG_ANSWER
LONG_ANSWER_CUT = "ร้อนตั้งแต่สายไปจนถึงค่ำทุก"


def sent_on_tap(message):
    """ข้อความที่ LINE จะส่งในนามผู้แจ้งเมื่อกดแต่ละปุ่ม — เฉพาะปุ่มชนิด message"""
    return [item.action.text for item in message.quick_reply.items if item.action.type == "message"]


async def test_answer_buttons_send_their_own_label_when_tapped(client, db, redis, outside, ai_answers, replies):
    """H13-1. AI ถามพร้อมปุ่ม message 2 ปุ่ม → quick reply 2 ปุ่มตามลำดับ · กดแล้ว LINE ส่งคำบนปุ่ม
    messages เก็บแค่ข้อความ · ai_calls เก็บ JSON ดิบ status ok"""
    raw = raw_answer(ASK_WHEN, AFTERNOON_BUTTON, ALL_DAY_BUTTON)
    await chat_one_round(client, redis, ai_answers, raw)

    [(_, [message])] = replies
    assert message.text == ASK_WHEN
    assert quick_reply_of(message) == [("message", "เฉพาะช่วงบ่ายค่ะ"), ("message", "ร้อนตลอดทั้งวันเลยค่ะ")]
    assert sent_on_tap(message) == ["เฉพาะช่วงบ่ายค่ะ", "ร้อนตลอดทั้งวันเลยค่ะ"]

    assert await db.fetchval("SELECT content FROM messages WHERE role = 'assistant'") == ASK_WHEN
    ai_call = await db.fetchrow("SELECT status, error, response FROM ai_calls")
    assert (ai_call["status"], ai_call["error"], ai_call["response"]) == ("ok", None, raw)


async def test_answer_button_and_pin_button_go_out_together(client, db, redis, outside, ai_answers, replies):
    """H13-2. ปุ่ม location กับปุ่ม message ในรอบเดียวกัน → อยู่ใน quick reply ทั้งคู่ เรียงตามที่ AI ให้"""
    await chat_one_round(client, redis, ai_answers, raw_answer(ASK_PIN, PIN_BUTTON, AFTERNOON_BUTTON))

    [(_, [message])] = replies
    assert quick_reply_of(message) == [("location", "แชร์ตำแหน่ง"), ("message", "เฉพาะช่วงบ่ายค่ะ")]
    assert sent_on_tap(message) == ["เฉพาะช่วงบ่ายค่ะ"]


async def test_thai_label_is_counted_the_way_it_is_seen(client, db, redis, outside, ai_answers, replies):
    """H13-3. คำบนปุ่มที่ตาเห็น 16 ตัวอักษร แต่ len() นับได้ 21 → ส่งคำเดิมครบ ไม่ถูกตัด · status ok"""
    assert len(ALL_DAY_BUTTON[1]) > 20
    await chat_one_round(client, redis, ai_answers, raw_answer(ASK_WHEN, ALL_DAY_BUTTON))

    [(_, [message])] = replies
    assert quick_reply_of(message) == [("message", "ร้อนตลอดทั้งวันเลยค่ะ")]
    ai_call = await db.fetchrow("SELECT status, error FROM ai_calls")
    assert (ai_call["status"], ai_call["error"]) == ("ok", None)


async def test_long_answer_button_is_cut_on_the_button_and_in_what_it_sends(
    client, db, redis, outside, ai_answers, replies
):
    """H13-4. คำบนปุ่ม message ยาวเกิน 20 ตัวอักษรที่ตาเห็น → คำบนปุ่มและข้อความที่ส่งเมื่อกด ถูกตัดเหลือ 20 ตัวแรกเท่ากัน
    สระและวรรณยุกต์ของตัวที่ 20 ยังอยู่ · status warning บอกชนิดปุ่ม · response ยังเป็นคำเต็ม"""
    raw = raw_answer(ASK_WHEN, AFTERNOON_BUTTON, ("message", LONG_ANSWER))
    await chat_one_round(client, redis, ai_answers, raw)

    [(_, [message])] = replies
    assert quick_reply_of(message) == [("message", "เฉพาะช่วงบ่ายค่ะ"), ("message", LONG_ANSWER_CUT)]
    assert sent_on_tap(message) == ["เฉพาะช่วงบ่ายค่ะ", LONG_ANSWER_CUT]

    ai_call = await db.fetchrow("SELECT status, error, response FROM ai_calls")
    assert ai_call["status"] == "warning"
    assert "message" in ai_call["error"]
    assert ai_call["response"] == raw


async def test_tapped_answer_comes_back_as_the_reporters_own_text(client, db, redis, outside, ai_answers, ai_calls):
    """H13-5. ผู้แจ้งกดปุ่มคำตอบ → LINE ส่งคำบนปุ่มมาเป็นข้อความ text → บันทึกเป็นข้อความของผู้แจ้ง
    รอบถัดไป AI เห็นคำถามของตัวเอง (ข้อความล้วน) แล้วตามด้วยคำบนปุ่ม"""
    await chat_one_round(client, redis, ai_answers, raw_answer(ASK_WHEN, AFTERNOON_BUTTON, ALL_DAY_BUTTON))

    tapped = ALL_DAY_BUTTON[1]
    await post_webhook(client, text_event(tapped, user_id="U_a", reply_token="rt-2", event_id="ev-2", message_id="m-2"))
    await run_next_job(redis)

    assert await db.fetchval("SELECT content FROM messages WHERE line_event_id = 'ev-2' AND role = 'user'") == tapped
    assert sent_to_ai(ai_calls[1]) == [
        ("system", "text", CHAT_PROMPT),
        ("user", "text", "น้ำท่วมหน้าบ้าน"),
        ("assistant", "text", ASK_WHEN),
        ("user", "text", tapped),
    ]


# --- #242 เลือกบน DB ได้ว่าจะใช้ ai_configs แถวไหน — spec ใน #242 · แบบ docs/designs/09-modules/242-select-ai-config.puml ---


async def test_chat_uses_the_active_config_not_the_newest_row(client, db, redis, outside, ai_config, ai_calls):
    """242-3. แถวที่ใช้ไม่ใช่แถวล่าสุด → ผู้แจ้งคุยหนึ่งรอบ → ตัวคุยได้ prompt และ model ของแถวที่ใช้ · ai_calls บันทึกแถวที่ใช้"""
    newer_model = await db.fetchval("INSERT INTO models (provider, name) VALUES ('test', 'newer-model') RETURNING model_id")
    newer_prompt = await db.fetchval("INSERT INTO prompts (prompt) VALUES ('newer prompt') RETURNING prompt_id")
    await db.execute(
        """
        INSERT INTO ai_configs (chat_model_id, chat_prompt_id, analyzer_model_id, analyzer_prompt_id)
        VALUES ($1, $2, $1, $2)
        """,
        newer_model,
        newer_prompt,
    )

    await accept_pdpa(client)
    await post_webhook(client, text_event("น้ำท่วมหน้าบ้าน", user_id="U_a", reply_token="rt-1", event_id="ev-1"))
    await run_next_job(redis)

    [(model, messages)] = ai_calls
    assert model == CHAT_MODEL
    assert messages[0].content == CHAT_PROMPT
    assert await db.fetchval("SELECT ai_config_id FROM ai_calls") == ai_config


# --- #239 ② เพดานข้อความใน buffer ต่อใบ — spec ใน #239 · แบบ docs/designs/09-modules/239-buffer-limit.puml ---


async def suspend(db, redis, session_id):
    """จำลอง controller พักใบ (239-buffer-limit): ข้อความของใบเป็น skipped · ล้าง buffer · state เป็น SUSPENDED 24 ชั่วโมง"""
    await db.execute("UPDATE messages SET status = 'skipped' WHERE session_id = $1", session_id)
    await redis.delete(f"session:{session_id}:buffer")
    await redis.set(f"session:{session_id}:state", "SUSPENDED", ex=24 * 60 * 60)


async def test_job_of_suspended_session_ends_without_ai(client, db, redis, outside, ai_calls, loadings, replies):
    """239②-7. ใบสั่งงานจากข้อความแรกยังรอเงียบ แล้วใบถูกพัก → worker จบงาน: ไม่เรียก AI · ไม่แสดง loading · ไม่ reply
    ไม่บันทึกคำตอบบอท · state ยังเป็น SUSPENDED"""
    await accept_pdpa(client)
    await post_webhook(client, text_event("น้ำท่วมหน้าบ้าน", user_id="U_a", reply_token="rt-1", event_id="ev-1"))
    session_id = await db.fetchval("SELECT session_id FROM sessions WHERE status = 'open'")
    await suspend(db, redis, session_id)

    await run_next_job(redis)

    assert ai_calls == []
    assert loadings == []
    assert replies == []
    assert await db.fetchval("SELECT count(*) FROM messages WHERE role = 'assistant'") == 0
    assert await redis.get(f"session:{session_id}:state") == "SUSPENDED"


async def test_suspended_while_ai_answers_still_replies_and_stays_suspended(
    client, db, redis, outside, ai_calls, replies, monkeypatch
):
    """239②-8. ใบถูกพักระหว่าง AI กำลังตอบ → บอท reply รอบนั้นตามปกติ · ข้อความของรอบนั้นเป็น answered
    state ยังเป็น SUSPENDED"""
    from app.clients import ai

    await accept_pdpa(client)
    await post_webhook(client, text_event("น้ำท่วมหน้าบ้าน", user_id="U_a", reply_token="rt-1", event_id="ev-1"))
    session_id = await db.fetchval("SELECT session_id FROM sessions WHERE status = 'open'")
    answer_from_ai = ai.chat  # AI ปลอมของ ai_calls

    async def suspended_meanwhile(model, messages, schema):
        await suspend(db, redis, session_id)
        return await answer_from_ai(model, messages, schema)

    monkeypatch.setattr(ai, "chat", suspended_meanwhile)

    await run_next_job(redis)

    [(reply_token, messages)] = replies
    assert reply_token == "rt-1"
    assert [message.text for message in messages] == [ANSWER]
    assert await db.fetchval("SELECT status FROM messages WHERE line_event_id = 'ev-1'") == "answered"
    assert await redis.get(f"session:{session_id}:state") == "SUSPENDED"


# --- #240 ข้อความที่เข้ามาระหว่างบอทกำลังตอบ ---


def user_texts(messages):
    """ข้อความของผู้แจ้งที่ส่งให้ AI ในครั้งนั้น"""
    return [m.content for m in messages if m.role == "user" and m.type == "text"]


async def test_message_during_ai_answer_gets_its_own_round(client, db, redis, outside, ai_calls, replies, monkeypatch):
    """240-1. ข้อความที่สองเข้ามาระหว่าง AI ตอบข้อความแรก → ยังอยู่ใน buffer · ได้งานคุยใหม่ · รอบใหม่ AI เห็น และตอบด้วย token ของมัน"""
    from app.clients import ai

    await accept_pdpa(client)
    await post_webhook(client, text_event("น้ำท่วมหน้าบ้าน", user_id="U_a", reply_token="rt-1", event_id="ev-1"))
    answer_from_ai = ai.chat

    async def second_message_meanwhile(model, messages, schema):
        if len(ai_calls) == 0:
            await post_webhook(
                client, text_event("ท่วมถึงเข่า", user_id="U_a", reply_token="rt-2", event_id="ev-2", message_id="m-2")
            )
        return await answer_from_ai(model, messages, schema)

    monkeypatch.setattr(ai, "chat", second_message_meanwhile)

    await run_next_job(redis)
    assert await redis.llen("jobs") == 1
    await run_next_job(redis)

    assert [token for token, _ in replies] == ["rt-1", "rt-2"]
    assert user_texts(ai_calls[1][1])[-1] == "ท่วมถึงเข่า"
    statuses = await db.fetch("SELECT status FROM messages WHERE role = 'user' ORDER BY created_at")
    assert [row["status"] for row in statuses] == ["answered", "answered"]


async def test_image_during_ai_answer_is_downloaded_and_reported(
    client, db, redis, outside, ai_calls, downloads, replies, monkeypatch
):
    """240-2. รูปเข้ามาระหว่าง AI ตอบ → รอบใหม่ดาวน์โหลดรูป · ปิดใบแล้วตัววิเคราะห์ทำงานได้ ไม่พัง"""
    from app.clients import ai
    from app.workers import worker

    await accept_pdpa(client)
    await post_webhook(client, text_event("น้ำท่วมหน้าบ้าน", user_id="U_a", reply_token="rt-1", event_id="ev-1"))
    session_id = await db.fetchval("SELECT session_id FROM sessions WHERE status = 'open'")
    answer_from_ai = ai.chat

    async def image_meanwhile(model, messages, schema):
        if len(ai_calls) == 0:
            await post_webhook(client, image_event(user_id="U_a", reply_token="rt-2", event_id="ev-2"))
        return await answer_from_ai(model, messages, schema)

    monkeypatch.setattr(ai, "chat", image_meanwhile)

    await run_next_job(redis)
    await run_next_job(redis)

    assert downloads == ["img-1"]
    assert await db.fetchval("SELECT count(*) FROM attachments") == 1
    transcript = await worker.session.read_transcript_for_analysis(session_id)
    await worker.prompt.build_analyse_context(await worker.prompt.active_config(), transcript)


# --- #213 AI พังหรือช้าระหว่างตอบ ---


def ai_breaks(monkeypatch):
    from app.clients import ai

    async def broken(model, messages, schema):
        raise RuntimeError("AI is down")

    monkeypatch.setattr(ai, "chat", broken)


async def test_ai_error_replies_fallback_and_keeps_buffer(client, db, redis, outside, replies, monkeypatch):
    """213-1. AI โยน error → ข้อความสำรองด้วย token ล่าสุด · state กลับ IDLE · buffer อยู่ครบ · ข้อความยัง pending · ไม่มีงานใหม่"""
    from app.workers.worker import FALLBACK_TEXT

    await accept_pdpa(client)
    await post_webhook(client, text_event("น้ำท่วมหน้าบ้าน", user_id="U_a", reply_token="rt-1", event_id="ev-1"))
    session_id = await db.fetchval("SELECT session_id FROM sessions WHERE status = 'open'")
    ai_breaks(monkeypatch)

    await run_next_job(redis)

    assert [(token, [m.text for m in messages]) for token, messages in replies] == [("rt-1", [FALLBACK_TEXT])]
    assert await redis.get(f"session:{session_id}:state") is None
    assert await redis.llen(f"session:{session_id}:buffer") == 1
    assert await db.fetchval("SELECT status FROM messages WHERE line_event_id = 'ev-1'") == "pending"
    assert await redis.llen("jobs") == 0


async def test_next_message_after_ai_error_sees_the_earlier_one(
    client, db, redis, outside, ai_calls, replies, monkeypatch
):
    """213-2. หลัง AI พัง ข้อความถัดไปได้งานคุย · AI เห็นทั้งข้อความที่ค้างและข้อความใหม่ · ผู้แจ้งไม่ต้องเล่าซ้ำ"""
    from app.clients import ai

    answer_from_ai = ai.chat
    await accept_pdpa(client)
    await post_webhook(client, text_event("น้ำท่วมหน้าบ้าน", user_id="U_a", reply_token="rt-1", event_id="ev-1"))
    ai_breaks(monkeypatch)
    await run_next_job(redis)

    monkeypatch.setattr(ai, "chat", answer_from_ai)
    await post_webhook(
        client, text_event("ตอบหน่อย", user_id="U_a", reply_token="rt-2", event_id="ev-2", message_id="m-2")
    )
    await run_next_job(redis)

    [(model, messages)] = ai_calls
    assert user_texts(messages)[-2:] == ["น้ำท่วมหน้าบ้าน", "ตอบหน่อย"]
    assert replies[-1][0] == "rt-2"
    statuses = await db.fetch("SELECT status FROM messages WHERE role = 'user' ORDER BY created_at")
    assert [row["status"] for row in statuses] == ["answered", "answered"]


async def test_slow_ai_counts_as_error(client, db, redis, outside, replies, monkeypatch):
    """213-3. AI ช้าเกิน AI_TIMEOUT_SECONDS → ข้อความสำรอง · state กลับ IDLE"""
    from app.clients import ai
    from app.workers import worker

    async def slow(model, messages, schema):
        await asyncio.sleep(5)

    monkeypatch.setattr(ai, "chat", slow)
    monkeypatch.setattr(worker, "AI_TIMEOUT_SECONDS", 0.1)
    await accept_pdpa(client)
    await post_webhook(client, text_event("น้ำท่วมหน้าบ้าน", user_id="U_a", reply_token="rt-1", event_id="ev-1"))
    session_id = await db.fetchval("SELECT session_id FROM sessions WHERE status = 'open'")

    await run_next_job(redis)

    assert [[m.text for m in messages] for _, messages in replies] == [[worker.FALLBACK_TEXT]]
    assert await redis.get(f"session:{session_id}:state") is None


async def test_ai_error_while_suspended_sends_nothing(client, db, redis, outside, replies, monkeypatch):
    """213-4. ใบถูกพักระหว่าง AI ตอบแล้ว AI พัง → ไม่มีข้อความสำรอง (controller ตอบข้อความแข็งไปแล้ว) · ยังเป็น SUSPENDED"""
    from app.clients import ai

    await accept_pdpa(client)
    await post_webhook(client, text_event("น้ำท่วมหน้าบ้าน", user_id="U_a", reply_token="rt-1", event_id="ev-1"))
    session_id = await db.fetchval("SELECT session_id FROM sessions WHERE status = 'open'")

    async def suspended_then_broken(model, messages, schema):
        await suspend(db, redis, session_id)
        raise RuntimeError("AI is down")

    monkeypatch.setattr(ai, "chat", suspended_then_broken)

    await run_next_job(redis)

    assert replies == []
    assert await redis.get(f"session:{session_id}:state") == "SUSPENDED"
    assert await redis.llen(f"session:{session_id}:buffer") == 0
