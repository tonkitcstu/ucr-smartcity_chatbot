"""ตาข่ายรองรับ — เก็บใบที่ใกล้หมดอายุก่อนมันหายไปเงียบ ๆ

ทำไมต้องมี: `draft` อยู่ใน Redis และมี TTL 1 ชั่วโมง ปกติใบจะปิดตอนที่ AI
บอกว่าครบแล้ว แต่ถ้า AI ลืมส่งธง no_location/no_photo มา หรือชาวบ้านหายไป
กลางทางไม่กลับมาอีกเลย ใบนั้นจะนอนอยู่จนหมดอายุแล้วหายไปทั้งใบ
**โดยที่ไม่มีใครรู้ว่าเคยมีอยู่** ชาวบ้านก็เชื่อว่าเล่าไปแล้ว

ตัวนี้เดินทุก SWEEP_EVERY วินาที มองหาใบที่ใกล้ตาย ถ้าใบนั้นมีของบังคับครบ
(categories กับ notes) ก็เก็บลงที่เก็บถาวรให้เลย ตำแหน่งหรือรูปจะขาดก็ช่าง
**ใบที่ไม่ครบดีกว่าใบที่ไม่มี** ส่วนใบที่ยังไม่มีเนื้อเรื่องอะไรเลยก็ปล่อยให้หมดอายุไป
เพราะไม่มีอะไรให้ทีมออกแบบอ่าน

ไฟล์นี้ไม่รู้จักช่องทางแชทและไม่รู้จักเว็บเฟรมเวิร์ก เหมือนไฟล์อื่นใน services/
"""

import asyncio
import logging

import asyncpg
from redis.asyncio import Redis

from app.clients import storage
from app.services import draft, lock, survey

log = logging.getLogger(__name__)

SWEEP_EVERY = 5 * 60      # กวาดทุก 5 นาที
RESCUE_UNDER = 10 * 60    # เหลืออายุน้อยกว่านี้ = ใกล้ตาย เก็บได้แล้ว


def _session_of(key: str) -> str | None:
    """`survey:U_alice` -> `U_alice` — ส่วน `survey:U_alice:done` ไม่ใช่ใบ ข้ามไป"""
    parts = key.split(":", 1)
    if len(parts) != 2 or parts[1].endswith(":done"):
        return None
    return parts[1]


async def rescue(r: Redis, pool: asyncpg.Pool) -> int:
    """กวาดหนึ่งรอบ คืนจำนวนใบที่เก็บทัน"""
    saved = 0

    async for key in r.scan_iter(match="survey:*", count=100):
        session_id = _session_of(key)
        if session_id is None:
            continue

        ttl = await r.ttl(key)
        if ttl < 0 or ttl > RESCUE_UNDER:
            continue

        try:
            # เขากำลังพิมพ์อยู่พอดี ปล่อยให้ตาของเขาจัดการไป เดี๋ยวรอบหน้าค่อยมาใหม่
            # ถ้าแย่งกันเก็บจะได้เรื่องเดียวกันสองใบ (ดู services/lock.py)
            async with lock.one_at_a_time(r, session_id, wait=0):
                saved += await _rescue_session(r, pool, session_id)
        except lock.Busy:
            continue

    return saved


async def close_open(
    r: Redis, pool: asyncpg.Pool, session_id: str, source: str = "rescued"
) -> int:
    """ปิดใบที่ค้างอยู่ตอนนี้ เก็บเท่าที่เขาเล่ามา — **ทางเดียวกับตอนกวาด**

    มีไว้ให้คนนอกเรียกตอนต้องตัดบทกลางคัน (เช่นชนเพดานโควตา) จะได้ไม่ต้องมี
    ตรรกะ "เก็บเท่าที่มี" สองชุดในโปรเจกต์ที่วันหลังจะเถียงกันเอง

    ตัวกวาดเรียก `_rescue_session` ตรง ๆ เพราะถือกุญแจอยู่แล้ว ซ้อนอีกชั้นจะค้าง
    """
    async with lock.one_at_a_time(r, session_id, wait=0):
        return await _rescue_session(r, pool, session_id, source)


async def _rescue_session(
    r: Redis, pool: asyncpg.Pool, session_id: str, source: str = "rescued"
) -> int:
    saved = 0

    for topic, report in (await draft.load_all(r, session_id)).items():
        if survey.missing(report):
            # ยังไม่มีเนื้อเรื่อง เก็บไปก็ไม่มีอะไรให้อ่าน ปล่อยหมดอายุไป
            continue

        report_id = await storage.save_report(
            pool,
            {
                "session_id": session_id,
                "source": source,
                **survey.public(report),
            },
        )
        await draft.remove(r, session_id, topic)
        saved += 1
        log.warning(
            "เก็บใบที่ยังไม่ครบไว้ทัน (%s) id=%s session=%s ขาด=%s",
            source,
            report_id,
            session_id,
            survey.next_goal(report),
        )

    return saved


async def run_forever(r: Redis, pool: asyncpg.Pool) -> None:
    """วนกวาดไปเรื่อย ๆ — ล้มแล้วต้องไม่ทำให้ทั้งแอปตายตาม"""
    while True:
        try:
            await asyncio.sleep(SWEEP_EVERY)
            await rescue(r, pool)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("กวาดใบใกล้หมดอายุไม่สำเร็จ รอบหน้าค่อยลองใหม่")
