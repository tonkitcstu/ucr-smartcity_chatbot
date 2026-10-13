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
# คำตอบดิบของ AI ตามรูปแบบ ChatAnswer (H10) — ข้อความ ANSWER ไม่มีปุ่ม
RAW_ANSWER = json.dumps({"text": ANSWER, "buttons": []}, ensure_ascii=False)
CHAT_PROMPT = "คุณคือน้องเมือง"
CHAT_MODEL = "test-chat-model"
IMAGE_BYTES = b"fake-jpg"


@pytest.fixture
async def ai_config(db):
    """ai_configs 1 ชุด — ตัวคุยกับตัววิเคราะห์ใช้ model / prompt เดียวกัน"""
    model_id = await db.fetchval(
        "INSERT INTO models (provider, name) VALUES ('test', $1) RETURNING model_id", CHAT_MODEL
    )
    prompt_id = await db.fetchval("INSERT INTO prompts (prompt) VALUES ($1) RETURNING prompt_id", CHAT_PROMPT)
    return await db.fetchval(
        """
        INSERT INTO ai_configs (chat_model_id, chat_prompt_id, analyzer_model_id, analyzer_prompt_id)
        VALUES ($1, $2, $1, $2) RETURNING ai_config_id
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
LONG_LABEL = "กดตรงนี้เพื่อแชร์ตำแหน่งที่เกิดเรื่องให้เมือง"
LABEL_MAX = 20


def raw_answer(text, *buttons):
    """คำตอบดิบของ AI ตามรูปแบบ ChatAnswer · ปุ่ม = (type, label)"""
    return json.dumps(
        {"text": text, "buttons": [{"type": kind, "label": label} for kind, label in buttons]}, ensure_ascii=False
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
    """H10-4. คำบนปุ่มยาว 20 ตัวอักษรพอดี → ส่งคำเดิมครบ · status ok"""
    label = LONG_LABEL[:LABEL_MAX]
    await chat_one_round(client, redis, ai_answers, raw_answer(ASK_PIN, ("location", label)))

    [(_, [message])] = replies
    assert quick_reply_of(message) == [("location", label)]
    ai_call = await db.fetchrow("SELECT status, error FROM ai_calls")
    assert (ai_call["status"], ai_call["error"]) == ("ok", None)


async def test_long_label_is_cut_and_button_still_sent_with_warning(client, db, redis, outside, ai_answers, replies):
    """H10-5. คำบนปุ่มยาวเกิน 20 → ส่ง 20 ตัวแรก ปุ่มและข้อความยังส่ง · ai_calls status warning บอกชนิดปุ่ม · response ยังเป็นคำเต็ม"""
    assert len(LONG_LABEL) > LABEL_MAX
    raw = raw_answer(ASK_PIN, ("location", LONG_LABEL))
    await chat_one_round(client, redis, ai_answers, raw)

    [(_, [message])] = replies
    assert message.text == ASK_PIN
    assert quick_reply_of(message) == [("location", LONG_LABEL[:LABEL_MAX])]

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


async def test_chat_ai_is_asked_for_text_and_three_button_types(client, db, redis, outside, ai_schemas):
    """H10-9. ตัวคุยถูกเรียกพร้อมรูปแบบคำตอบ: text + buttons · ชนิดปุ่มที่เลือกได้ = location, camera, camera_roll"""
    await accept_pdpa(client)
    await post_webhook(client, text_event("น้ำท่วมหน้าบ้าน", user_id="U_a", reply_token="rt-1", event_id="ev-1"))
    await run_next_job(redis)

    [schema] = ai_schemas
    described = schema.model_json_schema()
    assert set(described["properties"]) == {"text", "buttons"}
    button = described["$defs"]["QuickReplyButton"]
    assert set(button["properties"]) == {"type", "label"}
    assert button["properties"]["type"]["enum"] == ["location", "camera", "camera_roll"]


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
    """H10-11. AI ตอบมาแกะเป็น ChatAnswer ไม่ได้ → ai_calls status error มีเหตุ · response = ของดิบ · โยน error ต่อ (นอก happy path)"""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        await chat_one_round(client, redis, ai_answers, "ขอโทษค่ะ ตอนนี้ตอบไม่ได้")

    ai_call = await db.fetchrow("SELECT kind, status, error, response FROM ai_calls")
    assert (ai_call["kind"], ai_call["status"], ai_call["response"]) == ("communicator", "error", "ขอโทษค่ะ ตอนนี้ตอบไม่ได้")
    assert ai_call["error"]
