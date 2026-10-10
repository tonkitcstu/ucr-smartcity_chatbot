import asyncio
import os
import tempfile
from pathlib import Path

import asyncpg
import httpx
import pytest
from redis.asyncio import Redis

from tests.line_webhook import LINE_CHANNEL_SECRET

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "postgresql:///ucr_nongmuang_test")
TEST_REDIS_URL = os.getenv("TEST_REDIS_URL", "redis://localhost:6379/15")

# ต้องตั้งก่อน import app — config อ่าน env ตอน import
os.environ["LINE_CHANNEL_SECRET"] = LINE_CHANNEL_SECRET
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["REDIS_URL"] = TEST_REDIS_URL
# worker ไม่วนเองใน test — test หยิบงานแล้วเรียก run_chat เอง (H4)
os.environ["WORKER_ENABLED"] = "false"
os.environ["SILENCE_SECONDS"] = "0.3"
os.environ["UPLOADS_DIR"] = tempfile.mkdtemp(prefix="ucr-uploads-")
# กุญแจ JWT ของ test — ไม่ใช้ของจริงใน .env (H7)
os.environ["SECRET_KEY"] = "test-secret-key-shared-with-dashboard-team"
os.environ["ALGORITHM"] = "HS256"

SCHEMA = Path(__file__).resolve().parent.parent / "schema.sql"


async def _reset_schema():
    conn = await asyncpg.connect(TEST_DATABASE_URL)
    try:
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        await conn.execute(SCHEMA.read_text())
    finally:
        await conn.close()


@pytest.fixture(scope="session", autouse=True)
def schema():
    asyncio.run(_reset_schema())


@pytest.fixture
async def db():
    conn = await asyncpg.connect(TEST_DATABASE_URL)
    await conn.execute("TRUNCATE users RESTART IDENTITY CASCADE")
    yield conn
    await conn.close()


@pytest.fixture
async def redis():
    """Redis db 15 ล้างก่อนทุกข้อ"""
    conn = Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    await conn.flushdb()
    yield conn
    await conn.aclose()


@pytest.fixture
async def client(db, redis):
    from app.main import app

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.fixture
def replies(monkeypatch):
    """แทน clients/line.reply — จดว่าถูกเรียกด้วยอะไร ไม่ยิงไป LINE"""
    from app.clients import line

    calls = []

    async def fake_reply(reply_token, messages):
        calls.append((reply_token, messages))

    monkeypatch.setattr(line, "reply", fake_reply)
    return calls
