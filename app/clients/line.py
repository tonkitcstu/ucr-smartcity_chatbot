"""ภาษาของ LINE: ลายเซ็น, แกะ event, ปุ่มใต้ข้อความ, reply, push, loading animation, ดาวน์โหลดรูป"""

from linebot.v3 import WebhookParser
from linebot.v3.messaging import (
    AsyncApiClient,
    AsyncMessagingApi,
    AsyncMessagingApiBlob,
    CameraAction,
    CameraRollAction,
    Configuration,
    LocationAction,
    MessageAction,
    MulticastRequest,
    PushMessageRequest,
    QuickReply,
    QuickReplyItem,
    QuotaType,
    ReplyMessageRequest,
    ShowLoadingAnimationRequest,
    TextMessage,
)

from app.core.config import LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET
from app.models.line import QuickReplyButton
from app.models.user import User

parser = WebhookParser(LINE_CHANNEL_SECRET)
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)


def message_action(label: str) -> MessageAction:
    """ปุ่มคำตอบ: กดแล้ว LINE ส่งคำบนปุ่มเป็นข้อความของผู้แจ้ง"""
    return MessageAction(label=label, text=label)


# ปุ่มของเรา → action ของ LINE (location, camera, camera_roll LINE ให้ใช้เฉพาะใน quick reply)
ACTIONS = {
    "location": LocationAction,
    "camera": CameraAction,
    "camera_roll": CameraRollAction,
    "message": message_action,
}
# LINE รับ quick reply ได้สูงสุดกี่ปุ่มต่อข้อความ
QUICK_REPLY_MAX = 13
# LINE รับ multicast ได้สูงสุดกี่คนต่อคำขอ
MULTICAST_MAX = 500


def parse_events(body: str, signature: str) -> list:
    """เช็คลายเซ็นแล้วแกะ event · ลายเซ็นไม่ผ่าน → InvalidSignatureError"""
    return parser.parse(body, signature)


def build_quick_reply(buttons: list[QuickReplyButton]) -> QuickReply | None:
    """ปุ่มของเรา → ปุ่มใต้ข้อความของ LINE · ไม่มีปุ่ม → None · เกิน QUICK_REPLY_MAX → เอาชุดแรก"""
    if not buttons:
        return None
    return QuickReply(
        items=[
            QuickReplyItem(action=ACTIONS[button.type](label=button.label)) for button in buttons[:QUICK_REPLY_MAX]
        ]
    )


# ข้อความละกล่องตามลำดับ · ปุ่มอยู่ใต้ข้อความสุดท้าย เพราะ LINE แสดงปุ่มของข้อความสุดท้ายเท่านั้น
# ใช้ได้ทั้ง reply และ push
def text_messages(texts: list[str], buttons: list[QuickReplyButton]) -> list[TextMessage]:
    messages = [TextMessage(text=text) for text in texts[:-1]]
    messages.append(TextMessage(text=texts[-1], quick_reply=build_quick_reply(buttons)))
    return messages


async def reply(reply_token: str, messages: list) -> None:
    async with AsyncApiClient(configuration) as api_client:
        await AsyncMessagingApi(api_client).reply_message(
            ReplyMessageRequest(reply_token=reply_token, messages=messages)
        )


# ข้อความ push ที่ยังส่งได้อีกในเดือนนี้ · None = แผนของ LINE OA ไม่มีเพดาน
async def monthly_messages_left() -> int | None:
    async with AsyncApiClient(configuration) as api_client:
        api = AsyncMessagingApi(api_client)
        quota = await api.get_message_quota()
        if quota.type != QuotaType.LIMITED:
            return None
        used = await api.get_message_quota_consumption()
    return max(quota.value - used.total_usage, 0)


async def push(users: User | list[User], messages: list) -> None:
    """ส่งหาผู้แจ้งโดยไม่ต้องมี reply token · messages แบบเดียวกับที่ reply รับ · นับโควตาตามจำนวนคนรับ
    คนเดียว → push · หลายคน → multicast ข้อความชุดเดียวกัน กลุ่มละไม่เกิน MULTICAST_MAX · ไม่มีใคร → ไม่เรียก LINE"""
    to = [user.line_user_id for user in ([users] if isinstance(users, User) else users)]
    async with AsyncApiClient(configuration) as api_client:
        api = AsyncMessagingApi(api_client)
        if len(to) == 1:
            await api.push_message(PushMessageRequest(to=to[0], messages=messages))
            return
        for start in range(0, len(to), MULTICAST_MAX):
            await api.multicast(MulticastRequest(to=to[start : start + MULTICAST_MAX], messages=messages))


async def show_loading(line_user_id: str) -> None:
    """จุด ... กำลังพิมพ์ 60 วิ — หายเองตอน reply"""
    async with AsyncApiClient(configuration) as api_client:
        await AsyncMessagingApi(api_client).show_loading_animation(
            ShowLoadingAnimationRequest(chat_id=line_user_id, loading_seconds=60)
        )


async def download_message_content(line_message_id: str) -> bytes:
    """เนื้อไฟล์ของข้อความ (รูป) — LINE ลบทิ้งเองหลังผ่านไปสักพัก ต้องรีบเก็บ (TC9)"""
    async with AsyncApiClient(configuration) as api_client:
        return bytes(await AsyncMessagingApiBlob(api_client).get_message_content(line_message_id))
