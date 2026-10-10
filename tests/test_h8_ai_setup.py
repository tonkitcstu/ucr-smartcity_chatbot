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
    """3. มี ai_configs อยู่แล้ว (ไม่ใช่ค่า default) → เปิดแอป → ไม่เพิ่มแถว · แถวเดิมยังเป็นแถวล่าสุด"""
    model_id = await db.fetchval("INSERT INTO models (provider, name) VALUES ('test', 'own-model') RETURNING model_id")
    prompt_id = await db.fetchval("INSERT INTO prompts (prompt) VALUES ('own prompt') RETURNING prompt_id")
    own = await db.fetchval(
        """
        INSERT INTO ai_configs (chat_model_id, chat_prompt_id, analyzer_model_id, analyzer_prompt_id)
        VALUES ($1, $2, $1, $2) RETURNING ai_config_id
        """,
        model_id,
        prompt_id,
    )

    await open_app()

    assert await counts(db) == [1, 1, 1]
    assert await db.fetchval("SELECT ai_config_id FROM ai_configs ORDER BY created_at DESC LIMIT 1") == own


async def test_first_chat_uses_default_chat_prompt(empty_ai_tables, client, db, redis, monkeypatch, replies):
    """4. ฐานว่าง → เปิดแอป → ผู้แจ้งคุย 1 รอบ → ตัวคุยได้ system = CHAT_PROMPT · model = CHAT_MODEL"""
    from app.clients import ai, line
    from app.core import default_config
    from app.models.ai import AiReply
    from app.models.job import Job
    from app.workers import worker

    chats = []

    async def fake_chat(model, messages):
        chats.append((model, messages))
        return AiReply(text="น้ำสูงแค่ไหนคะ", input_tokens=1, output_tokens=1)

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
async def test_live_chat_answers_with_tokens():
    """5. LIVE_AI=1 · ai.chat กับ Gemini จริง → ได้ข้อความ + token"""
    from app.clients import ai
    from app.core import default_config
    from app.models.context import ContextMessage

    reply = await ai.chat(
        default_config.CHAT_MODEL,
        [
            ContextMessage(role="system", type="text", content=default_config.CHAT_PROMPT),
            ContextMessage(role="user", type="text", content="น้ำท่วมหน้าบ้านทุกครั้งที่ฝนตก"),
        ],
    )

    assert reply.text.strip()
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
