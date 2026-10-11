"""สมองของเส้น health: ถาม PSQL · Redis · worker · sweeper ว่ายังอยู่ไหม"""

import asyncio

from app.clients import database, redis
from app.models.health import HealthStatus


async def check(background: dict[str, asyncio.Task]) -> HealthStatus:
    """PSQL กับ Redis ออกไปถาม · worker กับ sweeper ดูจาก task ที่ lifespan เก็บไว้"""
    return HealthStatus(
        database=await database.ping(),
        redis=await redis.ping(),
        worker=is_running(background.get("worker")),
        sweeper=is_running(background.get("sweeper")),
    )


def is_running(task: asyncio.Task | None) -> bool:
    """ไม่มี task (WORKER_ENABLED ปิด) → False · task จบแล้ว (error พาหลุดจาก loop) → False · ยังวนอยู่ → True"""
    return task is not None and not task.done()
