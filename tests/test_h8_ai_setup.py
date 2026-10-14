"""H8 ต่อ AI ข้างนอก + ค่าเริ่มต้น prompt / model — TC5 · spec ใน #194 · แบบ docs/designs/09-modules/h8-ai-setup.puml"""

import os

import pytest

from tests.line_webhook import post_webhook, postback_event, text_event

live_ai = pytest.mark.skipif(os.getenv("LIVE_AI") != "1", reason="ยิง Gemini จริงเฉพาะ LIVE_AI=1")


@pytest.fixture
async def empty_ai_tables(db):
    """ฐานยังไม่มี ai_configs / models / prompts (ฐานใหม่ครั้งแรก)"""
    await db.execute("TRUNCATE ai_configs, models, prompts CASCADE")


async def open_app():
    """เปิดแอปแล้วปิด — lifespan หนึ่งรอบ"""
    from app.main import app

    async with app.router.lifespan_context(app):
        pass


async def config_rows(db):
    return await db.fetch(
        """
        SELECT c.ai_config_id,
               cm.provider AS chat_provider, cm.name AS chat_model, cp.prompt AS chat_prompt,
               am.provider AS analyser_provider, am.name AS analyser_model, ap.prompt AS analyser_prompt
        FROM ai_configs c
        JOIN models cm ON cm.model_id = c.chat_model_id
        JOIN prompts cp ON cp.prompt_id = c.chat_prompt_id
        JOIN models am ON am.model_id = c.analyzer_model_id
        JOIN prompts ap ON ap.prompt_id = c.analyzer_prompt_id
        ORDER BY c.created_at
        """
    )


async def counts(db):
    return [await db.fetchval(f"SELECT count(*) FROM {table}") for table in ("ai_configs", "models", "prompts")]


async def active_ids(db):
    """ai_config_id ของแถวที่ถูกเลือก (#242) — ถูกต้องเมื่อมีแถวเดียว"""
    return [row["ai_config_id"] for row in await db.fetch("SELECT ai_config_id FROM ai_configs WHERE is_active")]


async def test_empty_database_gets_default_config(db, redis, empty_ai_tables):
    """1. ฐานว่าง → เปิดแอป → ai_configs 1 · models 2 · prompts 2 ตรงกับ default_config"""
    from app.core import default_config

    await open_app()

    assert await counts(db) == [1, 2, 2]
    [row] = await config_rows(db)
    assert row["chat_provider"] == default_config.PROVIDER
    assert row["chat_model"] == default_config.CHAT_MODEL
    assert row["chat_prompt"] == default_config.CHAT_PROMPT
    assert row["analyser_provider"] == default_config.PROVIDER
    assert row["analyser_model"] == default_config.ANALYSER_MODEL
    assert row["analyser_prompt"] == default_config.ANALYSER_PROMPT


async def test_opening_app_again_adds_nothing(db, redis, empty_ai_tables):
    """2. เปิดแอปซ้ำ → ไม่เพิ่มแถว"""
    await open_app()
    await open_app()

    assert await counts(db) == [1, 2, 2]


async def test_existing_config_is_not_replaced(db, redis, empty_ai_tables):
    """3. มี ai_configs ที่ถูกเลือกอยู่แล้ว (ไม่ใช่ค่า default) → เปิดแอป → ไม่เพิ่มแถว · แถวเดิมยังเป็นแถวที่ใช้ (#242)"""
    model_id = await db.fetchval("INSERT INTO models (provider, name) VALUES ('test', 'own-model') RETURNING model_id")
    prompt_id = await db.fetchval("INSERT INTO prompts (prompt) VALUES ('own prompt') RETURNING prompt_id")
    own = await db.fetchval(
        """
        INSERT INTO ai_configs (chat_model_id, chat_prompt_id, analyzer_model_id, analyzer_prompt_id, is_active)
        VALUES ($1, $2, $1, $2, true) RETURNING ai_config_id
        """,
        model_id,
        prompt_id,
    )

    await open_app()

    assert await counts(db) == [1, 1, 1]
    assert await active_ids(db) == [own]


async def test_first_chat_uses_default_chat_prompt(empty_ai_tables, client, db, redis, monkeypatch, replies):
    """4. ฐานว่าง → เปิดแอป → ผู้แจ้งคุย 1 รอบ → ตัวคุยได้ system = CHAT_PROMPT · model = CHAT_MODEL"""
    from app.clients import ai, line
    from app.core import default_config
    from app.models.ai import AiReply
    from app.models.job import Job
    from app.workers import worker

    chats = []

    async def fake_chat(model, messages, schema):
        chats.append((model, messages))
        return AiReply(text='{"texts": ["น้ำสูงแค่ไหนคะ"], "buttons": []}', input_tokens=1, output_tokens=1)

    async def fake_show_loading(line_user_id):
        pass

    monkeypatch.setattr(ai, "chat", fake_chat)
    monkeypatch.setattr(line, "show_loading", fake_show_loading)

    await post_webhook(client, postback_event("pdpa_accept", user_id="U_a", event_id="ev-accept"))
    await post_webhook(client, text_event("น้ำท่วมหน้าบ้าน", user_id="U_a", event_id="ev-1"))
    await worker.run_chat(Job.model_validate_json(await redis.lpop("jobs")))

    [(model, messages)] = chats
    assert model == default_config.CHAT_MODEL
    assert (messages[0].role, messages[0].type, messages[0].content) == ("system", "text", default_config.CHAT_PROMPT)
    assert len(replies) == 1


@live_ai
async def test_live_chat_answers_in_chat_answer_format_with_tokens():
    """5 · H10-13 · H11-11. LIVE_AI=1 · ai.chat กับ Gemini จริงพร้อมรูปแบบ ChatAnswer → แกะเป็น ChatAnswer ผ่าน
    มีอย่างน้อย 1 ข้อความ ไม่มีข้อความว่าง · มี token"""
    from app.clients import ai
    from app.core import default_config
    from app.models.answer import ChatAnswer
    from app.models.context import ContextMessage

    reply = await ai.chat(
        default_config.CHAT_MODEL,
        [
            ContextMessage(role="system", type="text", content=default_config.CHAT_PROMPT),
            ContextMessage(role="user", type="text", content="น้ำท่วมหน้าบ้านทุกครั้งที่ฝนตก"),
        ],
        ChatAnswer,
    )

    answer = ChatAnswer.model_validate_json(reply.text)
    assert answer.texts
    assert all(text.strip() for text in answer.texts)
    assert reply.input_tokens
    assert reply.output_tokens


@live_ai
async def test_live_structured_matches_analysis():
    """6. LIVE_AI=1 · ai.structured กับ Gemini จริง → แกะด้วย Analysis ผ่าน"""
    from app.clients import ai
    from app.core import default_config
    from app.models.context import ContextMessage
    from app.models.report import Analysis

    reply = await ai.structured(
        default_config.ANALYSER_MODEL,
        [
            ContextMessage(role="system", type="text", content=default_config.ANALYSER_PROMPT),
            ContextMessage(role="user", type="text", content="ฝนตกทีไรน้ำท่วมหน้าบ้าน สูงเกือบเข่า"),
            ContextMessage(role="user", type="text", content="[ตำแหน่ง 1]"),
        ],
        Analysis,
    )

    analysis = Analysis.model_validate_json(reply.text)
    assert len(analysis.reports) >= 1


# --- H9 รับตำแหน่งและสติกเกอร์ — S4 S13 · spec ใน #219 · แบบ docs/designs/09-modules/h9-location-sticker.puml ---


def test_default_prompts_explain_system_notes():
    """H9-16. prompt ตัวคุยและตัววิเคราะห์อธิบายป้าย [ระบบ: ...] · prompt ตัวคุยพูดถึงสติกเกอร์"""
    from app.core import default_config

    assert "[ระบบ:" in default_config.CHAT_PROMPT
    assert "[ระบบ:" in default_config.ANALYSER_PROMPT
    assert "สติกเกอร์" in default_config.CHAT_PROMPT


# --- H10 ตัวคุยเลือกปุ่มใต้ข้อความ — S3 S4 · spec ใน #226 · แบบ docs/designs/09-modules/h10-quick-reply.puml ---


def test_default_chat_prompt_explains_buttons():
    """H10-12. prompt ตัวคุยบอกปุ่มทั้งสามชนิด และห้ามคำบนปุ่มยาวเกิน 20 ตัวอักษร"""
    from app.core import default_config

    for kind in ("location", "camera", "camera_roll"):
        assert kind in default_config.CHAT_PROMPT
    assert "20" in default_config.CHAT_PROMPT


# --- H11 ตัวคุยแยกคำตอบเป็นหลายข้อความ — milestone 2.0.1 ข้อ 2 · spec ใน #233 · แบบ docs/designs/09-modules/h11-multi-message.puml ---


def test_default_chat_prompt_explains_splitting_texts():
    """H11-10. prompt ตัวคุยบอกว่าตอบเป็น texts ได้หลายข้อความ และห้ามเกิน 5 ข้อความ"""
    from app.core import default_config

    assert "texts" in default_config.CHAT_PROMPT
    assert "5" in default_config.CHAT_PROMPT


# --- H13 ตัวคุยยื่นปุ่มคำตอบที่แต่งเอง — milestone 2.0.1 ข้อ 1 · spec ใน #237 · แบบ docs/designs/09-modules/h13-answer-buttons.puml ---


def test_default_chat_prompt_explains_answer_buttons():
    """H13-6. prompt ตัวคุยบอกปุ่มชนิด message และห้ามมีปุ่มข้าม"""
    from app.core import default_config

    assert "message" in default_config.CHAT_PROMPT
    assert "ข้าม" in default_config.CHAT_PROMPT.split("# ปุ่มใต้ข้อความ")[1].split("# ห้าม")[0]


# --- #242 เลือกบน DB ได้ว่าจะใช้ ai_configs แถวไหน — spec ใน #242 · แบบ docs/designs/09-modules/242-select-ai-config.puml ---


async def add_config(db, name):
    """ai_configs 1 แถว — model ชื่อ name · prompt เป็นคำว่า name · ยังไม่ถูกเลือก (is_active ใช้ค่าตั้งต้น)"""
    model_id = await db.fetchval("INSERT INTO models (provider, name) VALUES ('test', $1) RETURNING model_id", name)
    prompt_id = await db.fetchval("INSERT INTO prompts (prompt) VALUES ($1) RETURNING prompt_id", name)
    return await db.fetchval(
        """
        INSERT INTO ai_configs (chat_model_id, chat_prompt_id, analyzer_model_id, analyzer_prompt_id)
        VALUES ($1, $2, $1, $2) RETURNING ai_config_id
        """,
        model_id,
        prompt_id,
    )


async def choose(db, ai_config_id):
    """แอดมินเลือกแถวที่ใช้ — สองคำสั่งใน transaction เดียวตามแบบ: ปลดแถวเดิมก่อน แล้วตั้งแถวใหม่"""
    async with db.transaction():
        await db.execute("UPDATE ai_configs SET is_active = false WHERE is_active")
        await db.execute("UPDATE ai_configs SET is_active = true WHERE ai_config_id = $1", ai_config_id)


async def test_default_config_is_the_active_row(db, redis, empty_ai_tables):
    """242-1. ฐานว่าง → เปิดแอป → แถวค่าตั้งต้นเป็นแถวที่ใช้"""
    await open_app()

    [row] = await config_rows(db)
    assert await active_ids(db) == [row["ai_config_id"]]


async def test_rows_without_a_chosen_one_get_a_new_active_default(db, redis, empty_ai_tables):
    """242-2. มีแถวอยู่แล้วแต่ไม่มีแถวไหนถูกเลือก → เปิดแอป → ได้แถวค่าตั้งต้นใหม่เป็นแถวที่ใช้ · แถวเดิมยังอยู่ ไม่ถูกเลือก"""
    from app.core import default_config

    old = await add_config(db, "old")

    await open_app()

    assert await counts(db) == [2, 3, 3]
    [active] = await active_ids(db)
    assert active != old
    [row] = [row for row in await config_rows(db) if row["ai_config_id"] == active]
    assert row["chat_prompt"] == default_config.CHAT_PROMPT
    assert await db.fetchval("SELECT is_active FROM ai_configs WHERE ai_config_id = $1", old) is False


async def test_switching_rows_takes_effect_on_the_next_chat(empty_ai_tables, client, db, redis, monkeypatch, replies):
    """242-5. แอดมินสลับแถวด้วยสองคำสั่งใน transaction ระหว่างที่แอปเปิดอยู่ → งานคุยรอบถัดไปใช้แถวใหม่ ไม่ต้องเปิดแอปใหม่"""
    from app.clients import ai, line
    from app.models.ai import AiReply
    from app.models.job import Job
    from app.workers import worker

    models_used = []

    async def fake_chat(model, messages, schema):
        models_used.append(model)
        return AiReply(text='{"texts": ["น้ำสูงแค่ไหนคะ"], "buttons": []}', input_tokens=1, output_tokens=1)

    async def fake_show_loading(line_user_id):
        pass

    monkeypatch.setattr(ai, "chat", fake_chat)
    monkeypatch.setattr(line, "show_loading", fake_show_loading)
    first = await add_config(db, "first")
    second = await add_config(db, "second")

    await choose(db, first)
    await post_webhook(client, postback_event("pdpa_accept", user_id="U_a", event_id="ev-accept"))
    await post_webhook(client, text_event("น้ำท่วมหน้าบ้าน", user_id="U_a", event_id="ev-1"))
    await worker.run_chat(Job.model_validate_json(await redis.lpop("jobs")))

    await choose(db, second)
    await post_webhook(client, text_event("สูงประมาณเข่า", user_id="U_a", event_id="ev-2"))
    await worker.run_chat(Job.model_validate_json(await redis.lpop("jobs")))

    assert models_used == ["first", "second"]
