"""H4 Worker ตอบผู้แจ้ง — S2 S3 · spec ใน #152 · แบบ docs/designs/09-modules/h4-reply.puml"""

import asyncio
import json
from pathlib import Path

import pytest

from tests.line_webhook import image_event, post_webhook, postback_event, text_event

ANSWER = "น้ำสูงแค่ไหนครับ"
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
def ai_calls(monkeypatch):
    """แทน clients/ai.chat — คืน ANSWER · จดว่าได้ model กับ messages อะไร"""
    from app.clients import ai
    from app.models.ai import AiReply

    calls = []

    async def fake_chat(model, messages):
        calls.append((model, messages))
        return AiReply(text=ANSWER, input_tokens=10, output_tokens=5)

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
    assert ai_call["response"] == ANSWER

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


async def test_analyse_job_does_not_go_into_chat(client, db, redis, outside, ai_calls, replies):
    """5. งาน kind analyse เข้า handle → ไม่เรียก AI · ไม่ reply · ไม่พัง · ข้อความในใบไม่เปลี่ยน"""
    from app.models.job import Job
    from app.workers import worker

    await accept_pdpa(client)
    await post_webhook(client, text_event("น้ำท่วมหน้าบ้าน", user_id="U_a", reply_token="rt-1", event_id="ev-1"))
    await run_next_job(redis)
    [session] = await db.fetch("SELECT session_id FROM sessions WHERE status = 'open'")
    messages_before = await db.fetch("SELECT message_id, status FROM messages ORDER BY created_at")

    await worker.handle(Job(kind="analyse", session_id=session["session_id"]))

    assert len(ai_calls) == 1
    assert len(replies) == 1
    assert await db.fetchval("SELECT count(*) FROM ai_calls") == 1
    assert await db.fetch("SELECT message_id, status FROM messages ORDER BY created_at") == messages_before


async def test_chat_job_through_handle_gets_reply(client, db, redis, outside, ai_calls, replies):
    """6. งาน kind chat เข้า handle → คุยเหมือนเดิม: AI 1 ครั้ง · reply 1 ครั้ง"""
    from app.workers import worker

    await accept_pdpa(client)
    await post_webhook(client, text_event("ถนนหน้าบ้านเป็นหลุม", user_id="U_a", reply_token="rt-1", event_id="ev-1"))

    await worker.handle(await pop_job(redis))

    assert len(ai_calls) == 1
    assert [token for token, _ in replies] == ["rt-1"]
