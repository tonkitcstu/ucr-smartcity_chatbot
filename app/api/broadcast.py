"""หน้าและทางเข้าสำหรับ "ทักชาวบ้านก่อน" — เฟสแรกคนกดเอง ยังไม่มีตัวตั้งเวลา

ที่นี่ทำสองอย่างเท่านั้น: แปลงพารามิเตอร์จาก HTTP เป็นของธรรมดา แล้วยื่น
ฟังก์ชันส่งของช่องทางแชทให้สมองใช้ ตรรกะว่าใครควรได้รับอยู่ที่ services/broadcast.py

**ล็อกทั้ง router แล้ว** (issue #139) ก่อนหน้านี้ใครยิง URL ถูกก็สั่งทักชาวบ้านได้
ด่านเดียวที่มีคือ BROADCAST_ENABLED ซึ่ง **กั้นแค่ขาส่ง** — `/state` `/audience`
`/log` กับหน้า `/dashboard/broadcast` เปิดอ่านได้ตลอดไม่ว่าสวิตช์จะเปิดหรือปิด
แปลว่า**รายชื่อคนที่เราจะทักหลุดได้ทั้งที่คิดว่าปิดอยู่**

สองด่านนี้ทำคนละหน้าที่ ยังอยู่ด้วยกันทั้งคู่:
  guard              คุมว่า**ใคร**เข้าได้
  BROADCAST_ENABLED  คุมว่า**ตอนนี้ยิงของจริงได้หรือยัง** — คนที่ผ่านด่านแรก
                     มาแล้วก็ยังยิงไม่ได้ถ้าสวิตช์ปิด
"""

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from redis.asyncio import Redis

from app.api.deps import get_db, get_redis, guard
from app.clients import audience
from app.clients import line as line_client
from app.core.config import BASE_DIR, BROADCAST_ENABLED
from app.services import broadcast

router = APIRouter(dependencies=[Depends(guard)])

PAGE = BASE_DIR / "app" / "static" / "broadcast.html"


@router.get("/dashboard/broadcast")
async def page() -> FileResponse:
    return FileResponse(PAGE)


@router.get("/api/broadcast/state")
async def state(pool: asyncpg.Pool = Depends(get_db)) -> dict:
    """ทุกอย่างที่หน้าเว็บต้องรู้ก่อนวาดฟอร์ม — เรียกทีเดียวจบ

    `enabled` บอกหน้าเว็บว่าสวิตช์เปิดหรือยัง ให้ขึ้นป้ายเตือนได้ตั้งแต่ต้น
    ไม่ใช่ให้คนกรอกจนเสร็จแล้วค่อยเจอ 409
    """
    return {
        "enabled": BROADCAST_ENABLED,
        "topics": [
            {"id": name, "label": topic["label"]}
            for name, topic in broadcast.TOPICS.items()
        ],
        "communities": [
            row | {"members": len(await audience.members(pool, row["id"]))}
            for row in await audience.communities(pool)
        ],
    }


@router.get("/api/broadcast/audience")
async def who(pool: asyncpg.Pool = Depends(get_db)) -> list[dict]:
    """คนที่ทักได้ — ทุกคนที่เคยคุยกับเรา พร้อมชุมชนและวันที่ทักล่าสุด"""
    return await audience.known(pool)


@router.get("/api/broadcast/log")
async def log(pool: asyncpg.Pool = Depends(get_db)) -> list[dict]:
    """ทักใครไปบ้าง เขาตอบไหม ได้เรื่องกลับมาไหม"""
    return await audience.recent_pushes(pool)


@router.post("/api/broadcast/unblock")
async def unblock(to: str, r: Redis = Depends(get_redis)):
    """ปลดป้าย "เพิ่งคุยจบ" ของคนนี้ — สำหรับทดสอบ

    คนที่ทดสอบเองต้องคุยกับบอทก่อนถึงจะมีตัวตนให้ทัก แล้วก็ติดป้ายของตัวเอง
    ไปอีกครึ่งชั่วโมงทุกครั้ง ตรงนี้คือทางออกที่ไม่ต้องไปปิดกฎ

    **ไม่ลบใบที่คุยค้างอยู่** ป้ายปลดแล้วไม่มีอะไรหาย เรื่องลงตารางไปแล้ว
    แต่ใบที่ค้างยังไม่ได้ถูกเก็บที่ไหนเลย
    """
    return await broadcast.clear_recent(r, to)


@router.get("/api/broadcast/draft")
async def draft(topic: str, where: str | None = None) -> dict:
    """ให้ AI ร่างข้อความเปิด **ยังไม่ส่งไปไหน**

    มีไว้ให้คนอ่านก่อนกดส่ง — ข้อความนี้ไปโผล่ในแชทชาวบ้านจริง ๆ
    คนที่กดควรได้เห็นและแก้ได้ก่อน ไม่ใช่กดแล้วภาวนา
    """
    if topic not in broadcast.TOPICS:
        raise HTTPException(status_code=400, detail=f"เรื่องต้องเป็น {sorted(broadcast.TOPICS)}")

    try:
        return {"topic": topic, "text": await broadcast.opening(topic, where)}
    except broadcast.NoMessage as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/api/broadcast/send")
async def send_one(
    to: str,
    topic: str = "flood",
    text: str | None = None,
    force: bool = False,
    dry: bool = False,
    r: Redis = Depends(get_redis),
    pool: asyncpg.Pool = Depends(get_db),
):
    """ทักคนเดียว — `to` คือ LINE user id (ตัวเดียวกับ session_id ในตาราง reports)

    ไม่ใส่ `text` มาก็ให้ AI แต่งสดตอนส่ง
    """
    return await _fire(
        pool, r, dry,
        lambda send: broadcast.send_one(pool, r, to, topic, send, text=text, force=force),
    )


@router.post("/api/broadcast/run")
async def run(
    community: str,
    topic: str = "flood",
    text: str | None = None,
    force: bool = False,
    dry: bool = False,
    r: Redis = Depends(get_redis),
    pool: asyncpg.Pool = Depends(get_db),
):
    """ทักทั้งชุมชน

    dry   = ลองเปล่า ๆ ไม่ส่งจริง ไม่จดอะไรลง แค่บอกว่ารอบนี้จะไปถึงใคร
    force = ข้าม cap ทั้งสองชั้น (เดโม่เท่านั้น) — ไม่ข้ามข้อห้ามทักทับคนที่คุยค้างอยู่
    """
    return await _fire(
        pool, r, dry,
        lambda send: broadcast.run(pool, r, community, topic, send, text=text, force=force),
    )


async def _fire(pool, r, dry: bool, call):
    """ด่านสวิตช์ + เลือกว่าจะส่งจริงหรือลองเปล่า แล้วเรียกสมอง

    **ลองเปล่ายิงได้เสมอ แม้สวิตช์ปิดอยู่** เพราะมันไม่ส่งอะไรออกไปหาใคร
    """
    if not dry and not BROADCAST_ENABLED:
        raise HTTPException(
            status_code=409,
            detail="BROADCAST_ENABLED ยังปิดอยู่ — ตั้งใน .env แล้วรีสตาร์ทถึงจะส่งจริงได้",
        )

    async def send(recipients: list[str], text: str) -> dict:
        if dry:
            return {"sent": [], "failed": []}
        return await line_client.push_many(recipients, text)

    try:
        return await call(send) | {"dry": dry}
    except broadcast.NoMessage as exc:
        # โมเดลล่ม — ไม่มีข้อความสำรอง ตั้งใจ ดู services/broadcast.opening
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
