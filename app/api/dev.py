"""Endpoints for poking at things during development.

**ไฟล์นี้ไม่ขึ้น prod** — main.py ต่อ router นี้เฉพาะตอน DEV_ROUTES_ENABLED=true
ก่อนหน้านี้มันต่อทุกครั้งที่แอปเปิดโดยไม่มีอะไรกั้นเลย ซึ่งแปลว่าใครก็ตามที่รู้
URL ดึงใบทั้งตารางพร้อมพิกัดบ้านชาวบ้านได้ ล้างใบที่คนกำลังเล่าค้างอยู่ได้
และเผา quota โมเดลได้ฟรีสามทาง (issue #139)

ยังล็อกซ้ำอีกชั้นด้วย `guard` ตั้งใจ — เครื่อง dev ที่เผลอเปิดพอร์ตออกเน็ต
ไม่ควรกลายเป็นประตูเปิดโล่งเพราะสวิตช์ตัวเดียว ตัวที่เช็คสุขภาพย้ายไป api/health.py
เพราะมันต้องเรียกได้เสมอ
"""

import asyncpg
from fastapi import APIRouter, Depends
from redis.asyncio import Redis

from app.api.deps import get_db, get_redis, guard
from app.clients import llm, storage
from app.services import chat, draft, memory, survey

router = APIRouter(prefix="/api", dependencies=[Depends(guard)])


@router.get("/playground")
async def playground(message: str):
    return await llm.get_playground(message)


@router.get("/chat_test")
async def chat_test(
    message: str,
    session_id: str = "devtest",
    r: Redis = Depends(get_redis),
):
    """Playground + Redis memory. Same session_id keeps the conversation."""
    return await chat.reply(r, session_id, message)


@router.get("/survey")
async def survey_test(
    message: str,
    session_id: str = "devtest",
    latitude: float | None = None,
    longitude: float | None = None,
    location_text: str | None = None,
    image_key: str | None = None,
    source: str = "user",
    r: Redis = Depends(get_redis),
    pool: asyncpg.Pool = Depends(get_db),
):
    """น้องเมือง, without LINE. latitude/longitude/location_text stand in for the
    share-location button, image_key for a photo that was already stored;
    source is "broadcast" when replying to a card we pushed."""
    return await survey.reply(
        r,
        pool,
        session_id,
        message,
        latitude,
        longitude,
        location_text,
        image_key,
        source,
    )


@router.get("/survey/draft")
async def survey_draft(session_id: str = "devtest", r: Redis = Depends(get_redis)):
    """What has been collected so far, and what is still missing.

    One session can hold several reports at once, so "report"/"missing"/"next_goal"
    describe the one the bot should be asking about right now.
    """
    reports = await draft.load_all(r, session_id)
    spot = survey.focus(reports)
    topic = spot[0] if spot else None
    report = reports.get(topic, {})

    return {
        "topic": topic,
        "report": report,
        "missing": survey.missing(report),
        "next_goal": spot[1] if spot else None,
        "reports": {
            name: {
                "report": rep,
                "missing": survey.missing(rep),
                "next_goal": survey.next_goal(rep),
            }
            for name, rep in reports.items()
        },
        "ready": survey.ready(reports),
    }


@router.delete("/survey/draft")
async def survey_reset(session_id: str = "devtest", r: Redis = Depends(get_redis)):
    """Start the conversation over — as if this session had never said anything.

    ล้างป้าย "เพิ่งคุยจบ" ด้วย ไม่งั้นมันไม่ใช่การเริ่มใหม่จริง: บอทจะยังคิดว่า
    เพิ่งคุยกับคนนี้จบไปหมาด ๆ อยู่อีก 30 นาที และ broadcast จะข้ามคนนี้ทั้งที่
    ไม่มีอะไรค้างแล้ว — **นี่คือวิธีเว้นด่านนั้นตอนทดสอบ** ดู services/broadcast.py
    """
    await draft.clear(r, session_id)
    await draft.clear_done(r, session_id)
    await memory.clear(r, session_id)
    return {"cleared": session_id}


@router.get("/reports")
async def reports(pool: asyncpg.Pool = Depends(get_db)):
    """Everything that made it to the permanent store."""
    return await storage.list_reports(pool)
