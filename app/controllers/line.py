"""สมองของ webhook LINE: เช็คลายเซ็น แกะ event แล้วแยกตามชนิด"""

from linebot.v3.webhooks import (
    FollowEvent,
    ImageMessageContent,
    LocationMessageContent,
    MessageEvent,
    PostbackEvent,
    StickerMessageContent,
    TextMessageContent,
    UnfollowEvent,
)

from app.clients import line
from app.models.line import IncomingMessage
from app.services import job, pdpa, quota, session, state, user

async def handle_webhook(body: str, signature: str) -> None:
    """ลายเซ็นไม่ผ่าน → InvalidSignatureError · event ชนิดอื่นข้าม"""
    for event in line.parse_events(body, signature):
        if isinstance(event, FollowEvent):
            await on_follow(event)
        elif isinstance(event, UnfollowEvent):
            await user.mark_blocked(event.source.user_id)
        elif isinstance(event, PostbackEvent):
            await on_postback(event)
        elif isinstance(event, MessageEvent):
            await on_message(event)


async def on_follow(event: FollowEvent) -> None:
    """ส่งการ์ด PDPA · ยังไม่เก็บอะไรของเขา · เคยยอมรับแล้วเลิกบล็อก → ได้ข้อความทักอีก
    ตอบการ์ดก่อนแตะฐาน · ฐานมีปัญหาผู้แจ้งก็ยังได้การ์ด"""
    await line.reply(event.reply_token, [pdpa.card()])
    await user.mark_following(event.source.user_id)


async def on_postback(event: PostbackEvent) -> None:
    # กดยอมรับ → สร้าง User แล้วตอบข้อความตายตัวว่าเริ่มคุยได้เลย · กดซ้ำได้ข้อความเดิมอีกครั้ง
    if event.postback.data == pdpa.ACCEPT:
        await pdpa.accept(event.source.user_id)
        await line.reply(event.reply_token, [pdpa.welcome_message()])


async def on_message(event: MessageEvent) -> None:
    """ยังไม่ยอมรับ → ส่งการ์ดอีกครั้ง ไม่เก็บข้อความ ไม่ส่ง AI (LC1)
    ยอมรับแล้ว → บันทึก ต่อ buffer · IDLE → BUFFERING ได้ → ใส่ใบสั่งงานคุย · ไม่ reply (worker ตอบ)
    ใบถูกพักอยู่ (#239 ②) → บันทึกเป็น skipped แล้ว reply ข้อความแข็ง · เช็คก่อนเพดานอื่น
    ใช้ token วันนี้ถึงเพดานแล้ว (#239 ①) → บันทึก แล้ว reply ข้อความแข็ง · ไม่ต่อ buffer ไม่แตะ state ไม่ใส่ใบสั่งงาน
    buffer ของใบครบเพดานแล้ว (#239 ②) → ข้อความที่ค้างและข้อความนี้เป็น skipped · ล้าง buffer · พักใบ · reply ข้อความแข็ง
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
    if await state.is_suspended(current.session_id):
        await session.skip(current, message)
        await line.reply(event.reply_token, [quota.suspended_message()])
        return
    if await quota.is_over_daily_limit(found) or await quota.is_over_system_daily_limit():
        await line.reply(event.reply_token, [quota.limit_reached_message()])
        return
    if await quota.is_buffer_full(current):
        await session.skip(current, message)
        await state.suspend(current)
        await line.reply(event.reply_token, [quota.suspended_message()])
        return

    await session.buffer(message)
    if await state.start_buffering(current.session_id):
        await job.enqueue_chat(current.session_id)


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
