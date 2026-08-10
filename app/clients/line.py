"""ส่งข้อความกลับ LINE

นาฬิกา 2 เรือนที่ต้องจำ
  2 วินาที  = ต้องตอบ 200 กลับ LINE ให้ทัน — เรื่องนั้นจัดการที่ api/line.py
  1 นาที    = อายุ reply token ทันใช้ reply (ฟรี) ไม่ทันต้อง push (กินโควตา)
"""

import logging

from linebot.v3.messaging import (
    AsyncApiClient,
    AsyncMessagingApi,
    AsyncMessagingApiBlob,
    CameraAction,
    CameraRollAction,
    Configuration,
    LocationAction,
    PushMessageRequest,
    QuickReply,
    QuickReplyItem,
    ReplyMessageRequest,
    ShowLoadingAnimationRequest,
    TextMessage,
)

from app.core.config import LINE_CHANNEL_ACCESS_TOKEN

log = logging.getLogger(__name__)

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)

# ปุ่มลัด โผล่เฉพาะตาที่บอทกำลังขอของนั้นอยู่ กดง่ายกว่าให้เขาหาเมนูเอง
_LOCATION_BUTTON = QuickReply(
    items=[QuickReplyItem(action=LocationAction(label="ส่งตำแหน่ง"))]
)

# ให้ทั้งสองทาง — เรื่องที่เกิดอยู่ตอนนี้ถ่ายสด เรื่องเมื่อวานหยิบจากอัลบั้ม
_PHOTO_BUTTONS = QuickReply(
    items=[
        QuickReplyItem(action=CameraAction(label="ถ่ายรูป")),
        QuickReplyItem(action=CameraRollAction(label="เลือกจากอัลบั้ม")),
    ]
)


def _message(text: str, ask_location: bool, ask_photo: bool) -> TextMessage:
    """ปุ่มขึ้นได้ชุดเดียว ตำแหน่งมาก่อนเสมอ — ไม่มีพิกัด = ไม่ขึ้นหมุดบนแผนที่"""
    quick_reply = None
    if ask_location:
        quick_reply = _LOCATION_BUTTON
    elif ask_photo:
        quick_reply = _PHOTO_BUTTONS

    return TextMessage(text=text, quickReply=quick_reply)


async def reply(
    reply_token: str, text: str, ask_location: bool = False, ask_photo: bool = False
) -> None:
    async with AsyncApiClient(configuration) as api_client:
        await AsyncMessagingApi(api_client).reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[_message(text, ask_location, ask_photo)],
            )
        )


async def push(
    to: str, text: str, ask_location: bool = False, ask_photo: bool = False
) -> None:
    """ใช้ตอน reply token หมดอายุแล้ว — อันนี้กินโควตารายเดือนของ OA"""
    async with AsyncApiClient(configuration) as api_client:
        await AsyncMessagingApi(api_client).push_message(
            PushMessageRequest(
                to=to,
                messages=[_message(text, ask_location, ask_photo)],
            )
        )


# ------------------------------------------------ ตอนเราเป็นฝ่ายเปิดเรื่องก่อน


async def push_many(recipients: list[str], text: str) -> dict:
    """ส่งข้อความเดียวกันให้ทุกคนในรายชื่อ คืนว่าถึงใคร พลาดใคร

    ข้อความล้วน ไม่มีการ์ด ไม่มีปุ่ม — **เขาตอบเป็นภาษาคน ไม่ใช่กดตัวเลือก**

    **ทีละคน และคนที่พลาดต้องไม่ลากคนที่เหลือลงไปด้วย** คนหนึ่งบล็อกบอทไปแล้ว
    อีกร้อยคนที่เหลือไม่เกี่ยว ของเดิมไม่มี try ตรงนี้ คนเดียว throw = ทั้งรอบตาย

    ส่งเรียงทีละคนไม่ส่งพร้อมกัน เพราะ push กินโควตารายเดือนของ OA และ LINE
    มีเพดานต่อวินาทีอยู่ — เรียงช้ากว่าแต่ไม่มีใครหล่น
    """
    result = {"sent": [], "failed": []}
    if not recipients:
        return result

    async with AsyncApiClient(configuration) as api_client:
        api = AsyncMessagingApi(api_client)
        for to in recipients:
            try:
                await api.push_message(
                    PushMessageRequest(to=to, messages=[TextMessage(text=text)])
                )
                result["sent"].append(to)
            except Exception:
                log.warning("ส่งไม่ถึง to=%s ข้ามไปคนถัดไป", to, exc_info=True)
                result["failed"].append(to)

    return result


async def send(
    reply_token: str,
    to: str,
    text: str,
    ask_location: bool = False,
    ask_photo: bool = False,
) -> None:
    """ลอง reply ก่อนเพราะฟรี ไม่ได้ค่อย push

    reply พังได้หลายทาง (token หมดอายุ / ถูกใช้ไปแล้ว) ซึ่งเรารู้ตอนยิงเท่านั้น
    เลยดักตรงนี้แล้วเปลี่ยนไปใช้ push แทน ดีกว่าเงียบหายไปเฉย ๆ

    **push นับเข้าโควตาข้อความรายเดือน ส่วน reply ไม่นับ** โควตาก้อนเดียวกันนี้
    คือก้อนที่ broadcast จะใช้ ตกมา push บ่อยเมื่อไหร่แปลว่าเรากินโควตาของ
    broadcast ไปเรื่อย ๆ โดยไม่มีใครเห็น — log บรรทัดนี้คือที่เดียวที่บอกได้
    """
    try:
        await reply(reply_token, text, ask_location, ask_photo)
    except Exception:
        log.warning(
            "reply ไม่สำเร็จ ตกไปใช้ push แทน (กินโควตารายเดือนก้อนเดียวกับ broadcast) to=%s",
            to,
            exc_info=True,
        )
        await push(to, text, ask_location, ask_photo)


async def download_image(message_id: str) -> bytes:
    """โหลดรูปที่ชาวบ้านส่งมา — LINE เก็บไว้ให้ชั่วคราว ต้องรีบมาเอา"""
    async with AsyncApiClient(configuration) as api_client:
        return await AsyncMessagingApiBlob(api_client).get_message_content(message_id)


async def show_loading(chat_id: str, seconds: int = 60) -> None:
    """จุดสามจุดกระพริบระหว่างรอ AI คิด — ได้เฉพาะแชท 1:1 กลุ่มใช้ไม่ได้

    ล้มเหลวได้โดยไม่เป็นไร มันเป็นแค่ของประดับ ห้ามทำให้ข้อความจริงไม่ถูกส่ง

    **เดิม 20 วินาที ซึ่งสั้นกว่าตาที่ช้าจริง ๆ** ตาปกติ 8-12 วินาทีก็จริง
    แต่ตาที่มี tool หลายรอบไปได้ถึง 80 (4 call × timeout 20 ดู clients/llm.py)
    จุดหายไปแล้วบอทยังไม่ตอบ = เขาอ่านว่าเครื่องค้าง แล้วพิมพ์ซ้ำ ซึ่งไปติดคิว
    lock ต่ออีก ยาวไปกันใหญ่ ยืดเป็นเพดานสูงสุดที่ LINE ให้ (60) ไปเลย
    มันดับเองตอนข้อความจริงถึง ตั้งเผื่อไว้จึงไม่มีข้อเสีย
    """
    try:
        async with AsyncApiClient(configuration) as api_client:
            await AsyncMessagingApi(api_client).show_loading_animation(
                ShowLoadingAnimationRequest(chatId=chat_id, loadingSeconds=seconds)
            )
    except Exception:
        log.debug("แสดง loading ไม่ได้ ข้ามไป", exc_info=True)
