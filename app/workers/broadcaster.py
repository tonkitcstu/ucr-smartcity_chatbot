# สมองเบื้องหลังของการทักไปก่อน
# ทุกวันหลังตี 1 อ่านพยากรณ์อากาศ · วันไหนฝนจะตกหรือร้อนเกิน 35 องศา พอถึง 8 โมงเช้าให้ตัวคุยแต่งข้อความแล้วทักผู้แจ้งทีละคน
# วันละไม่เกิน BROADCAST_DAILY_LIMIT คน · แบบ docs/diagrams/broadcast-flow.mmd
# ตื่นมาดูเวลาทุก BROADCAST_CHECK_SECONDS แบบเดียวกับตัวกวาดใบ · วันนี้ทำถึงไหนแล้วดูจากแถวของวันนี้ใน broadcasts
#   แอปดับแล้วเปิดใหม่จึงทำต่อจากที่ค้างได้ และไม่ทักซ้ำ

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.clients import line
from app.core.config import BROADCAST_CHECK_SECONDS, BROADCAST_FETCH_AT, BROADCAST_SEND_AT, BROADCAST_SEND_UNTIL
from app.models.broadcast import Broadcast
from app.models.session import Session
from app.models.user import User
from app.services import broadcast, communicator, prompt, quota, session

THAI_TIME = timezone(timedelta(hours=7))
# รอ AI แต่งข้อความทักได้ไม่เกินนี้ · ไม่มี reply token ให้ต้องรีบ แต่ไม่ให้คนหนึ่งค้างจนคนที่เหลือไม่ได้ทัก
AI_TIMEOUT_SECONDS = 60

logger = logging.getLogger(__name__)


# วนไม่จบ · ดูหนึ่งรอบแล้วหลับ BROADCAST_CHECK_SECONDS
async def run() -> None:
    while True:
        try:
            await tick(datetime.now(THAI_TIME))
        except Exception:
            # พังรอบนี้ เช่น อ่านพยากรณ์ไม่ได้ → รอบหน้าลองใหม่ ตัวทักไม่หยุดวน
            logger.exception("ตัวทักไปก่อนพัง")
        await asyncio.sleep(BROADCAST_CHECK_SECONDS)


# ดูหนึ่งรอบว่าตอนนี้ต้องทำอะไร · now เป็นเวลาไทย (test ส่งเวลาที่อยากลองเข้ามาเองได้)
async def tick(now: datetime) -> None:
    if now.time() < BROADCAST_FETCH_AT:
        return
    today = await broadcast.find_for(now.date())
    if today is None:
        today = await broadcast.check_forecast(now.date())
    if today.status != "scheduled" or now.time() < BROADCAST_SEND_AT:
        return
    if now.time() >= BROADCAST_SEND_UNTIL:
        await broadcast.mark_expired(today)
        return
    # ยังเป็น scheduled อยู่ = ยังไม่ได้ทัก หรือทักค้างไว้เพราะแอปดับกลางทาง · ไล่ทักใหม่ คนที่ได้ไปแล้วถูกข้าม
    await greet_everyone(today)
    await broadcast.mark_sent(today)


# ทักทีละคนที่ broadcast.recipients เลือก · ทักคนไหนพังก็ข้ามไปคนถัดไป
# งบ token ของตัวคุยทั้งระบบวันนี้หมด (#239) → หยุด คนที่เหลือไม่ได้ข้อความ
async def greet_everyone(today: Broadcast) -> None:
    for recipient in await broadcast.recipients(today):
        if await quota.is_over_system_daily_limit():
            logger.warning("งบ token ทั้งระบบของวันนี้หมด หยุดทัก")
            return
        opened = await broadcast.open_session_for(recipient, today)
        if opened is None:
            continue
        try:
            await greet(recipient, opened, today)
        except Exception:
            logger.exception("ทักใบ %s ไม่ผ่าน", opened.session_id)


# ตัวคุยแต่งข้อความทักเองทุกครั้ง (ห้ามข้อความสำเร็จรูป) โดยรู้เหตุที่ทักจากบรรทัด [ระบบ: ...]
# ส่งแล้วบันทึกแบบเดียวกับรอบคุยปกติ ผู้แจ้งตอบกลับมาในใบนี้แล้วตัวคุยเห็นว่าตัวเองทักอะไรไป
async def greet(recipient: User, opened: Session, today: Broadcast) -> None:
    config = await prompt.active_config()
    note = prompt.broadcast_note(today.reason)
    messages = await prompt.build_chat_context(config, [], [note])
    async with asyncio.timeout(AI_TIMEOUT_SECONDS):
        answer = await communicator.chat(opened.session_id, config, messages)
    await line.push(recipient, line.text_messages(answer.texts, answer.buttons))
    # ไม่มีข้อความของผู้แจ้งใน buffer · ประวัติของใบ = บรรทัดเหตุที่ทัก + ข้อความที่ทักไป
    await session.finish(opened.session_id, [], [note], answer.texts)
