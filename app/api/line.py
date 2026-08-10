"""LINE webhook: เช็คลายเซ็น แกะกล่อง แล้วโยนงานให้สมอง

**ต้องตอบ 200 กลับ LINE ภายใน 2 วินาที** ไม่งั้นนับเป็น error ฝั่ง LINE
AI คิดนานกว่านั้นแน่ เลยตอบ 200 ทันทีแล้วให้ BackgroundTasks ไปคุยต่อเบื้องหลัง
(reply token ยังมีอายุ 1 นาที ทันสบาย)

ไฟล์นี้คือที่เดียวที่รู้จักกล่องของ LINE — งานแกะทั้งหมดจบตรงนี้
สมองข้างในรับแค่ str กับตัวเลข
"""

import logging

import asyncpg
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import (
    ImageMessageContent,
    LocationMessageContent,
    MessageEvent,
    TextMessageContent,
)
from redis.asyncio import Redis

from app.api.deps import get_db, get_redis
from app.clients import line as line_client
from app.clients import media
from app.core.config import LINE_CHANNEL_SECRET
from app.services import broadcast, burst, lock, quota, survey, sweeper

log = logging.getLogger(__name__)

router = APIRouter()

parser = WebhookParser(LINE_CHANNEL_SECRET)

# ข้อความตอนระบบเราเองมีปัญหา — พูดเหมือนน้องเมืองพูด ไม่ใช่หน้าจอ error
# ห้ามบอกว่าเก็บเรื่องให้แล้ว เพราะตอนนี้เราไม่รู้เลยว่าเก็บทันหรือเปล่า
TROUBLE = (
    "ขอโทษนะคะ ตอนนี้ระบบทางนี้ขัดข้องอยู่ "
    "รบกวนพิมพ์มาใหม่อีกทีในอีกสักพักได้ไหมคะ 🙏"
)

# ตาก่อนหน้ายังทำไม่เสร็จ และรอจนหมดเวลาแล้ว — คนละเรื่องกับ TROUBLE
# ระบบไม่ได้พัง แค่ยังไม่ว่าง บอกให้ตรงจะได้ไม่ต้องเดา
BUSY = (
    "ขอโทษนะคะ ข้อความก่อนหน้านี้เมืองยังตอบไม่เสร็จเลยค่ะ "
    "รอสักครู่แล้วส่งข้อความเมื่อกี้มาใหม่อีกทีได้ไหมคะ 🙏"
)

# เรื่องเล่าจบครบแล้วแต่เก็บลงที่เก็บถาวรไม่ได้ — เขาต้องไม่เดินจากไปโดยเชื่อว่าเรียบร้อยแล้ว
NOT_SAVED = (
    "\n\n(ขออภัยค่ะ ตอนนี้ระบบบันทึกขัดข้องอยู่ เรื่องนี้ยังไม่ได้ลงระบบ "
    "เมืองเก็บไว้ให้แล้วและจะพยายามบันทึกอีกครั้งเองนะคะ)"
)


def session_id(event: MessageEvent) -> str:
    """หนึ่งใบต่อหนึ่งห้องแชท — กลุ่มใช้ร่วมกัน แชทเดี่ยวแยกตามคน"""
    source = event.source
    return (
        getattr(source, "group_id", None)
        or getattr(source, "room_id", None)
        or source.user_id
    )


def is_direct(event: MessageEvent) -> bool:
    """แชท 1:1 หรือเปล่า — loading animation ใช้ได้เฉพาะแบบนี้"""
    return getattr(event.source, "group_id", None) is None and (
        getattr(event.source, "room_id", None) is None
    )


def unwrap(event: MessageEvent) -> dict | None:
    """แกะกล่องเป็นของธรรมดา คืน None ถ้าเป็นชนิดที่เรายังไม่รับ (สติกเกอร์ เสียง วิดีโอ)"""
    message = event.message

    if isinstance(message, TextMessageContent):
        return {"said": message.text}

    if isinstance(message, LocationMessageContent):
        # พิกัดไม่เข้าโมเดลตรง ๆ ข้างในจะแปลงเป็น marker ให้เอง
        # ชื่อสถานที่เอาจาก LINE เลย เชื่อถือได้กว่าให้โมเดลสรุปเอง
        return {
            "said": "ส่งตำแหน่งมาให้แล้ว",
            "latitude": message.latitude,
            "longitude": message.longitude,
            "location_text": message.address or message.title,
        }

    if isinstance(message, ImageMessageContent):
        # ตัวรูปยังไม่โหลดตรงนี้ เพราะต้องรีบตอบ 200 ให้ทัน 2 วิ ไปโหลดเบื้องหลัง
        #
        # **ไม่ใส่ข้อความปลอมแทนตัวรูป** เคยใส่ว่า "ส่งรูปมาให้" แล้วโมเดลนึกว่า
        # เป็นคำที่ชาวบ้านพิมพ์มาเอง เลยลอกไปเขียนใน notes — ได้ใบที่เรื่องเล่าเขียนว่า
        # "แดดร้อนที่ทางเข้าชุมชน ส่งรูปมาให้ดูด้วย" ทั้งที่ไม่มีใครพูดท่อนหลัง
        # ข้างในจะเติม marker [ระบบ: …] ให้แทน ซึ่งแยกออกว่าไม่ใช่คำของคน
        return {"said": "", "image_id": message.id}

    return None


@router.post("/callback")
async def callback(
    request: Request,
    background_tasks: BackgroundTasks,
    x_line_signature: str = Header(...),
    r: Redis = Depends(get_redis),
    pool: asyncpg.Pool = Depends(get_db),
):
    # ลายเซ็นคิดจาก body ดิบ ต้องอ่านก่อนแปลง
    body = (await request.body()).decode()

    try:
        events = parser.parse(body, x_line_signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    for event in events:
        if not isinstance(event, MessageEvent):
            continue

        unwrapped = unwrap(event)
        if unwrapped is None:
            continue

        background_tasks.add_task(
            answer,
            r,
            pool,
            session_id(event),
            event.reply_token,
            is_direct(event),
            unwrapped,
        )

    # ตอบทันที ห้ามรอ AI
    return "OK"


async def answer(
    r: Redis,
    pool: asyncpg.Pool,
    session: str,
    reply_token: str,
    direct: bool,
    incoming: dict,
) -> None:
    """ทำงานหลังตอบ 200 ไปแล้ว — ตรงนี้ช้าได้"""
    if direct:
        await line_client.show_loading(session)

    try:
        photos = 0
        if image_id := incoming.get("image_id"):
            # LINE เก็บรูปให้ชั่วคราว ต้องรีบมาเอาก่อนหมดอายุ
            content = await line_client.download_image(image_id)
            image_key = await media.save(image_id, content)
            onto_closed = await survey.attach_photo(r, pool, session, image_key)

            # **เขากดส่งทีเดียว 3 ใบ แต่ LINE ยิงมาให้เราทีละใบ** การซอยเป็นสามครั้ง
            # เป็นเรื่องภายในของ LINE ไม่ใช่สิ่งที่เขาทำ ถ้าตอบทุกใบเขาจะโดนเด้ง
            # 3 ข้อความจากการกดครั้งเดียว รอให้ชุดครบก่อน ใบสุดท้ายเป็นคนพูดแทนทั้งชุด
            photos = await burst.settled(r, session)
            if not photos:
                return

            if onto_closed:
                # รูปไปเกาะเรื่องที่ปิดไปแล้ว ไม่มีอะไรค้างให้คุยต่อ
                await line_client.send(reply_token, session, survey.PHOTO_ADDED)
                return

        # ── ด่านโควตา — ต้องอยู่ตรงนี้ หลังงานรูป ก่อนเรียกโมเดล ───────────
        #
        # งานแนบรูปข้างบนไม่เรียกโมเดลเลย (ดู attach_photo) เลยไม่ควรโดนกั้น
        # ชนเพดานแล้วยังส่งรูปเข้าใบที่เล่าไว้ได้ตามปกติ
        if not (gate := await quota.allowed(r, session))["go"]:
            log.warning(
                "โควตากั้นไว้ session=%s โซน=%s เพราะ=%s เล่าค้างอยู่=%s",
                session,
                gate["zone"],
                gate["reason"],
                gate["mid_draft"],
            )

            # แดงตอนเขาเล่าค้างอยู่ — **ปิดใบเก็บเท่าที่เล่ามา อย่าปล่อยให้หายไปเงียบ ๆ**
            # ทางเดียวกับตัวกวาด: ใบที่ยังไม่มีเนื้อเรื่องปล่อยไป ใบที่มีเก็บลงถาวร
            # ("ใบที่ไม่ครบดีกว่าใบที่ไม่มี" — ดู services/sweeper.py)
            saved = 0
            if gate["zone"] == quota.RED and gate["mid_draft"]:
                try:
                    saved = await sweeper.close_open(r, pool, session, source="capped")
                except Exception:
                    log.exception("ปิดใบตอนชนเพดานไม่สำเร็จ session=%s", session)

            # เก็บเรื่องเขาไว้แล้วต้องบอกเขา ไม่งั้นเขาเดินจากไปโดยไม่รู้ว่าถึงมือเรา
            await line_client.send(
                reply_token, session, await quota.notice(r, gate["zone"], saved > 0)
            )
            return

        result = await survey.reply(
            r,
            pool,
            session,
            incoming["said"],
            latitude=incoming.get("latitude"),
            longitude=incoming.get("longitude"),
            location_text=incoming.get("location_text"),
            # ตานี้เป็นการตอบกลับที่เราทักไปหรือเปล่า — จดว่าเขาตอบแล้วด้วย
            source=await broadcast.source_of(pool, r, session),
            photos=photos,
        )

        # ใบที่เกิดจากการที่เราทักไป ผูกกลับไปที่แถวการทักครั้งนั้น
        for report_id in result["report_ids"]:
            await broadcast.link_report(pool, r, session, report_id)

        # ── บวกตัวนับ **หลังคุยจบ** เพราะก่อนคุยยังไม่รู้ว่าตานี้กินเท่าไหร่ ──
        await quota.spend(r, session, result["used"])

        # ไม่เหลือใบค้างแล้ว = เริ่มนับ cap ต่อใบใหม่ ไม่งั้นคนที่เล่าสองเรื่องติดกัน
        # จะลากยอดของใบแรกมาชนเพดานกลางเรื่องที่สอง
        if not result["reports"]:
            await quota.clear_draft(r, session)

    except lock.Busy:
        # เดิมตัวนี้ตกลงไปกิน `except Exception` ข้างล่าง ชาวบ้านเลยเห็น
        # "ระบบขัดข้อง" ทั้งที่ระบบไม่ได้ขัดข้องอะไรเลย แค่ตาก่อนหน้ายังไม่จบ
        # และเราไม่มีทางแยกออกจาก log ด้วยว่าวันนั้นเป็นเพราะอะไร
        #
        # ตาปกติวัดได้ 8-12 วินาที ไม่มีทางชน WAIT_SECONDS=45 — จะชนก็ต่อเมื่อ
        # ตาก่อนหน้าค้างผิดปกติ ซึ่งเกิดขึ้นได้จริงตอนโดน 429 รัว ๆ
        log.warning("ตาก่อนหน้ายังไม่จบ รอไม่ไหวแล้ว session=%s", session)
        await line_client.send(reply_token, session, BUSY)
        return
    except Exception:
        # Redis ล่ม AI ไม่ตอบ ดิสก์เต็ม — อะไรก็ตามที่เราไม่ได้เตรียมไว้
        # ตรงนี้ทำงานหลังตอบ 200 ไปแล้ว ถ้าปล่อยให้ตายเงียบ **ชาวบ้านจะเห็นแค่ความเงียบ**
        # แล้วไม่มีทางรู้เลยว่าที่พิมพ์ไปถึงหรือไม่ถึง บอกไปตรง ๆ ดีกว่า
        log.exception("ตอบไม่สำเร็จ session=%s", session)
        await line_client.send(reply_token, session, TROUBLE)
        return

    text = result["reply"]
    if result["store_broke"]:
        text += NOT_SAVED

    await line_client.send(
        reply_token,
        session,
        text,
        ask_location=result["asking_location"],
        ask_photo=result["asking_photo"],
    )

    # ให้ AI แต่งข้อความโซนเหลืองเก็บไว้ตอนที่ยังเรียกมันได้ ข้างในเช็คเองว่า
    # มีของสดอยู่แล้วหรือยัง — วันละครั้ง ไม่ได้ยิงทุกตา
    #
    # **ต้องอยู่หลังส่ง ไม่ใช่ก่อน** เดิมอยู่ในบล็อก try ข้างบน แปลว่าคนแรกของวัน
    # ต้องรอโมเดลอีกรอบเต็ม ๆ ก่อนจะได้เห็นคำตอบของตัวเอง ทั้งที่ของที่รออยู่
    # ไม่เกี่ยวกับเขาเลย — และมันคือ request ที่ 3 ของข้อความแรกในวันที่เพดาน
    # มีแค่ 15 ต่อนาที (ดู clients/llm.py)
    #
    # ล้มแล้วต้องไม่ทำอะไรพัง ข้อความจริงส่งไปแล้ว ข้างในกลืน error ของตัวเอง
    # อยู่แล้ว แต่กันไว้อีกชั้นเพราะตรงนี้ไม่มี except ครอบให้แล้ว
    try:
        if gate["zone"] == quota.GREEN:
            await quota.refresh_notice(r)
    except Exception:
        log.warning("เตรียมข้อความโซนเหลืองไม่สำเร็จ", exc_info=True)
