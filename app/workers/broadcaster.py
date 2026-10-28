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
from app.models.answer import ChatAnswer
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


# ทักทีละคนที่ broadcast.recipients เลือก · ทุกคนได้ข้อความเดียวกันที่ตัวคุยแต่งครั้งเดียวต่อวัน
# แต่งในใบของคนแรก (ai_calls ต้องมีใบ) แล้วจดไว้ที่แถวของวันนั้น · แอปดับแล้วทักต่อใช้ข้อความเดิม
# แต่งหรือส่งให้คนไหนไม่ผ่านก็ข้ามไปคนถัดไป · ยังไม่มีข้อความ คนถัดไปให้ตัวคุยแต่งใหม่
# ยังต้องแต่งแต่งบ token ของตัวคุยทั้งระบบวันนี้หมด (#239) → ไม่ทักใคร
async def greet_everyone(today: Broadcast) -> None:
    greeting = today.greeting
    if greeting is None and await quota.is_over_system_daily_limit():
        logger.warning("งบ token ทั้งระบบของวันนี้หมด ไม่ทัก")
        return
    for recipient in await broadcast.recipients(today):
        opened = await broadcast.open_session_for(recipient, today)
        if opened is None:
            continue
        try:
            if greeting is None:
                greeting = await write_greeting(opened, today)
            await greet(recipient, opened, today, greeting)
        except Exception:
            logger.exception("ทักใบ %s ไม่ผ่าน", opened.session_id)


# ตัวคุยแต่งข้อความทักเอง (ห้ามข้อความสำเร็จรูป) โดยรู้เหตุที่ทักจากบรรทัด [ระบบ: ...] แล้วจดไว้ที่แถวของวันนั้น
async def write_greeting(opened: Session, today: Broadcast) -> ChatAnswer:
    config = await prompt.active_config()
    messages = await prompt.build_chat_context(config, [], [prompt.broadcast_note(today.reason)])
    async with asyncio.timeout(AI_TIMEOUT_SECONDS):
        greeting = await communicator.chat(opened.session_id, config, messages)
    await broadcast.save_greeting(today, greeting)
    return greeting


# ส่งแล้วบันทึกแบบเดียวกับรอบคุยปกติ ผู้แจ้งตอบกลับมาในใบนี้แล้วตัวคุยเห็นว่าตัวเองทักอะไรไป
async def greet(recipient: User, opened: Session, today: Broadcast, greeting: ChatAnswer) -> None:
    await line.push(recipient, line.text_messages(greeting.texts, greeting.buttons))
    # ไม่มีข้อความของผู้แจ้งใน buffer · ประวัติของใบ = บรรทัดเหตุที่ทัก + ข้อความที่ทักไป
    await session.finish(opened.session_id, [], [prompt.broadcast_note(today.reason)], greeting.texts)
