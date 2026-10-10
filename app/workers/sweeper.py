"""กวาดใบที่เงียบ: ปิดใบ แล้วใส่งานวิเคราะห์"""

import asyncio

from app.core.config import SWEEP_EVERY_SECONDS
from app.models.session import Session
from app.services import job, session


async def run() -> None:
    """วนไม่จบ · กวาดหนึ่งรอบแล้วหลับ SWEEP_EVERY_SECONDS"""
    while True:
        await sweep()
        await asyncio.sleep(SWEEP_EVERY_SECONDS)


async def sweep() -> None:
    """ทุกใบที่เงียบ · ได้ใบไปปิด (IDLE → CLOSING) → finish_closing · กำลังคุยอยู่ → ข้าม"""
    for silent in await session.find_silent():
        if await session.start_closing(silent):
            await finish_closing(silent)


async def finish_closing(silent: Session) -> None:
    """ใบที่เป็น CLOSING แล้ว · ปิดสำเร็จ → งานวิเคราะห์
    ปิดไม่สำเร็จ (มีข้อความเข้ามาระหว่าง CLOSING) → คืนใบ · มีข้อความรอ → งานคุย ผู้แจ้งยังได้คำตอบ"""
    if await session.close(silent):
        await job.enqueue_analyse(silent)
        return
    await session.stop_closing(silent)
    if await session.has_buffer(silent) and await session.start_buffering(silent):
        await job.enqueue_chat(silent)
