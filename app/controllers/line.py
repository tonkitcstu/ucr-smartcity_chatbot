"""สมองของ webhook LINE: เช็คลายเซ็น แกะ event แล้วแยกตามชนิด"""

from linebot.v3.webhooks import FollowEvent, MessageEvent, PostbackEvent, TextMessageContent

from app.clients import line
from app.models.message import IncomingMessage
from app.services import job, pdpa, session, user


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
    await session.buffer(message)
    if await session.start_buffering(current):
        await job.enqueue_chat(current)


def to_incoming(event: MessageEvent) -> IncomingMessage | None:
    """ข้อความ text → IncomingMessage · ชนิดอื่น → None (รูปเพิ่มใน H3)"""
    if not isinstance(event.message, TextMessageContent):
        return None
    return IncomingMessage(
        line_event_id=event.webhook_event_id,
        line_message_id=event.message.id,
        reply_token=event.reply_token,
        type="text",
        content=event.message.text,
    )
