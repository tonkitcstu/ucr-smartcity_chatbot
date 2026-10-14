"""schema.sql — ของที่ฐานต้องมีก่อนแอปเปิด · #208"""

import asyncpg
import pytest


async def test_postgis_is_installed(db):
    """1. รัน schema.sql แล้วฐานมี PostGIS — ถามเชิงพื้นที่ได้ (ระยะระหว่างสองจุดเป็นเมตร)"""
    assert await db.fetchval("SELECT extname FROM pg_extension WHERE extname = 'postgis'") == "postgis"

    metres = await db.fetchval(
        """
        SELECT ST_Distance(
            ST_SetSRID(ST_MakePoint(100.5018, 13.7563), 4326)::geography,
            ST_SetSRID(ST_MakePoint(100.5018, 13.7653), 4326)::geography
        )
        """
    )
    assert 900 < metres < 1100


async def test_only_one_ai_config_can_be_active(db):
    """242-6. ai_configs มีแถวที่ใช้ได้แถวเดียว — insert แถวที่สองที่ is_active = true ฐานปฏิเสธ · #242"""
    model_id = await db.fetchval("INSERT INTO models (provider, name) VALUES ('test', 'test-model') RETURNING model_id")
    prompt_id = await db.fetchval("INSERT INTO prompts (prompt) VALUES ('test prompt') RETURNING prompt_id")
    insert_active = """
        INSERT INTO ai_configs (chat_model_id, chat_prompt_id, analyzer_model_id, analyzer_prompt_id, is_active)
        VALUES ($1, $2, $1, $2, true)
    """
    await db.execute("UPDATE ai_configs SET is_active = false WHERE is_active")
    await db.execute(insert_active, model_id, prompt_id)

    with pytest.raises(asyncpg.UniqueViolationError):
        await db.execute(insert_active, model_id, prompt_id)


async def test_user_daily_token_limit_defaults_to_two_million(db):
    """239-8. insert แถว ai_configs โดยไม่ใส่เพดาน → user_daily_token_limit = 2,000,000 · #239"""
    model_id = await db.fetchval("INSERT INTO models (provider, name) VALUES ('test', 'test-model') RETURNING model_id")
    prompt_id = await db.fetchval("INSERT INTO prompts (prompt) VALUES ('test prompt') RETURNING prompt_id")

    limit = await db.fetchval(
        """
        INSERT INTO ai_configs (chat_model_id, chat_prompt_id, analyzer_model_id, analyzer_prompt_id)
        VALUES ($1, $2, $1, $2) RETURNING user_daily_token_limit
        """,
        model_id,
        prompt_id,
    )

    assert limit == 2_000_000
