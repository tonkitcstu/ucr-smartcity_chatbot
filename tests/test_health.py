"""health เส้นเช็คว่า PSQL · Redis · worker · sweeper ยังอยู่ — T2 · spec ใน #206 · แบบ docs/designs/09-modules/health.puml"""

import asyncio
from contextlib import asynccontextmanager

import asyncpg
import httpx
from redis.asyncio import Redis

HEALTH = "/health"
ALL_ALIVE = {"database": True, "redis": True, "worker": True, "sweeper": True}

# port ที่ไม่มีใครฟัง — ต่อไม่ได้ทันที ไม่ต้องปิด PSQL / Redis ตัวจริง
NO_DATABASE_URL = "postgresql://localhost:1/nothing"
NO_REDIS_URL = "redis://localhost:1/15"


@asynccontextmanager
async def open_app():
    """เปิดแอปหลังจัดฉากเสร็จ — worker กับ sweeper เริ่มวนตอนเปิด"""
    from app.main import app

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield client


def enable_workers(monkeypatch):
    """conftest ปิด worker กับ sweeper ไว้ — ข้อที่ต้องมีทั้งคู่เปิดเอง"""
    from app import main

    monkeypatch.setattr(main, "WORKER_ENABLED", True)


async def wait_forever():
    await asyncio.Event().wait()


def stand_in(monkeypatch, module):
    """แทน run() ด้วยตัวที่รอเฉย ๆ ไม่จบ — ข้อนั้นไม่ได้เทสตัวนี้"""
    monkeypatch.setattr(module, "run", wait_forever)


async def test_all_alive_answers_200(db, redis, monkeypatch):
    """1. worker กับ sweeper ตัวจริงวนอยู่ · PSQL กับ Redis ตอบ → 200 · true ครบ · ไม่ต้องมี JWT"""
    enable_workers(monkeypatch)

    async with open_app() as client:
        await asyncio.sleep(0.1)
        response = await client.get(HEALTH)

    assert response.status_code == 200
    assert response.json() == ALL_ALIVE


async def test_database_unreachable_answers_503(db, redis, monkeypatch):
    """2. PSQL ต่อไม่ได้ → 503 · database false ช่องเดียว"""
    from app.clients import database
    from app.workers import sweeper, worker

    enable_workers(monkeypatch)
    stand_in(monkeypatch, worker)
    stand_in(monkeypatch, sweeper)
    unreachable = await asyncpg.create_pool(NO_DATABASE_URL, min_size=0)

    async with open_app() as client:
        with monkeypatch.context() as patch:
            patch.setattr(database, "pool", unreachable)
            response = await client.get(HEALTH)
    await unreachable.close()

    assert response.status_code == 503
    assert response.json() == ALL_ALIVE | {"database": False}


async def test_redis_unreachable_answers_503(db, redis, monkeypatch):
    """3. Redis ต่อไม่ได้ → 503 · redis false ช่องเดียว"""
    from app.clients import redis as redis_client
    from app.workers import sweeper, worker

    enable_workers(monkeypatch)
    stand_in(monkeypatch, worker)
    stand_in(monkeypatch, sweeper)
    unreachable = Redis.from_url(NO_REDIS_URL, decode_responses=True)

    async with open_app() as client:
        with monkeypatch.context() as patch:
            patch.setattr(redis_client, "client", unreachable)
            response = await client.get(HEALTH)
    await unreachable.aclose()

    assert response.status_code == 503
    assert response.json() == ALL_ALIVE | {"redis": False}


async def test_dead_worker_answers_503(db, redis, monkeypatch):
    """4. worker ตัวจริงหยิบงานแล้วเจอ error (Redis หลุดตอนรอคิว) → run() จบ → 503 · worker false ช่องเดียว"""
    from app.clients import redis as redis_client
    from app.workers import sweeper

    async def pop_job_fails():
        raise ConnectionError("Redis หลุดตอนรอคิว")

    enable_workers(monkeypatch)
    stand_in(monkeypatch, sweeper)
    monkeypatch.setattr(redis_client, "pop_job", pop_job_fails)

    async with open_app() as client:
        await asyncio.sleep(0.1)
        response = await client.get(HEALTH)

    assert response.status_code == 503
    assert response.json() == ALL_ALIVE | {"worker": False}


async def test_dead_sweeper_answers_503(db, redis, monkeypatch):
    """5. sweeper ตัวจริงกวาดแล้วเจอ error (PSQL หลุดตอนหาใบที่เงียบ) → run() จบ → 503 · sweeper false ช่องเดียว"""
    from app.clients import database
    from app.workers import worker

    async def select_silent_sessions_fails(minutes):
        raise OSError("PSQL หลุดตอนหาใบที่เงียบ")

    enable_workers(monkeypatch)
    stand_in(monkeypatch, worker)
    monkeypatch.setattr(database, "select_silent_sessions", select_silent_sessions_fails)

    async with open_app() as client:
        await asyncio.sleep(0.1)
        response = await client.get(HEALTH)

    assert response.status_code == 503
    assert response.json() == ALL_ALIVE | {"sweeper": False}


async def test_workers_not_started_answers_503(db, redis):
    """6. WORKER_ENABLED ปิด — แอปไม่ได้เปิด worker กับ sweeper → 503 · worker กับ sweeper false"""
    async with open_app() as client:
        response = await client.get(HEALTH)

    assert response.status_code == 503
    assert response.json() == ALL_ALIVE | {"worker": False, "sweeper": False}
