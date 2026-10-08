"""สมองของ webhook LINE: เช็คลายเซ็น แกะ event แล้วแยกตามชนิด"""

from linebot.v3.webhooks import FollowEvent, MessageEvent, PostbackEvent

from app.clients import line
from app.services import pdpa, user


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
    """ยังไม่ยอมรับ → ส่งการ์ดอีกครั้ง ไม่เก็บข้อความ ไม่ส่ง AI (LC1)"""
    found = await user.find_by_line_id(event.source.user_id)
    if found is None:
        await line.reply(event.reply_token, [pdpa.card()])
        return
    # ยอมรับแล้ว → H2 (#160)
