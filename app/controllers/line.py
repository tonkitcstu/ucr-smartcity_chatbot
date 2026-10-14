"""สมองของ webhook LINE: เช็คลายเซ็น แกะ event แล้วแยกตามชนิด"""

from linebot.v3.webhooks import (
    FollowEvent,
    ImageMessageContent,
    LocationMessageContent,
    MessageEvent,
    PostbackEvent,
    StickerMessageContent,
    TextMessageContent,
)

from app.clients import line
from app.models.line import IncomingMessage
from app.services import job, pdpa, quota, session, user

async def handle_webhook(body: str, signature: str) -> None:
    """ลายเซ็นไม่ผ่าน → InvalidSignatureError · event ชนิดอื่นข้าม"""
    for event in line.parse_events(body, signature):
        if isinstance(event, FollowEvent):
            await on_follow(event)
        elif isinstance(event, PostbackEvent):
            await on_postback(event)
        elif isinstance(event, MessageEvent):
            await on_message(event)


async def on_follow(event: FollowEvent) -> None:
    """ส่งการ์ด PDPA · ยังไม่เก็บอะไรของเขา"""
    await line.reply(event.reply_token, [pdpa.card()])


async def on_postback(event: PostbackEvent) -> None:
    """กดยอมรับ → สร้าง User · ไม่ตอบ (ปุ่มมี displayText ให้เขาเห็นแล้วว่ากด)"""
    if event.postback.data == pdpa.ACCEPT:
        await pdpa.accept(event.source.user_id)


async def on_message(event: MessageEvent) -> None:
    """ยังไม่ยอมรับ → ส่งการ์ดอีกครั้ง ไม่เก็บข้อความ ไม่ส่ง AI (LC1)
    ยอมรับแล้ว → บันทึก ต่อ buffer · IDLE → BUFFERING ได้ → ใส่ใบสั่งงานคุย · ไม่ reply (worker ตอบ)
    ใช้ token วันนี้ถึงเพดานแล้ว (#239) → บันทึก แล้ว reply ข้อความแข็ง · ไม่ต่อ buffer ไม่แตะ state ไม่ใส่ใบสั่งงาน
    """
    found = await user.find_by_line_id(event.source.user_id)
    if found is None:
        await line.reply(event.reply_token, [pdpa.card()])
        return

    incoming = to_incoming(event)
    if incoming is None:
        return

    current = await session.open_for(found)
    message = await session.save_message(current, incoming)
    if await quota.is_over_daily_limit(found):
        await line.reply(event.reply_token, [quota.limit_reached_message()])
        return

    await session.buffer(message)
    if await session.start_buffering(current):
        await job.enqueue_chat(current)


def to_incoming(event: MessageEvent) -> IncomingMessage | None:
    """ข้อความ text → type text · รูป → type image ไม่มี content (worker ดาวน์โหลดด้วย line_message_id)
    ตำแหน่ง → type location มี lat/lng · สติกเกอร์ → type sticker content = keywords ที่ LINE ใช้บรรยาย (ไม่ส่งมา = ไม่มี)
    ชนิดอื่น → None"""
    # availible message_type
    message_types = {
        TextMessageContent: "text",
        ImageMessageContent: "image",
        LocationMessageContent: "location",
        StickerMessageContent: "sticker",
    }
    message = event.message
    kind = message_types.get(type(message))
    if kind is None:
        return None
    content = lat = lng = None
    if kind == "text":
        content = message.text
    elif kind == "location":
        lat, lng = message.latitude, message.longitude
    elif kind == "sticker" and message.keywords:
        content = ", ".join(message.keywords)
    return IncomingMessage(
        line_event_id=event.webhook_event_id,
        line_message_id=message.id,
        reply_token=event.reply_token,
        type=kind,
        content=content,
        lat=lat,
        lng=lng,
    )
