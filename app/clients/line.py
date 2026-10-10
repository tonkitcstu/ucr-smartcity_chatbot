"""ภาษาของ LINE: ลายเซ็น, แกะ event, reply, loading animation, ดาวน์โหลดรูป"""

from linebot.v3 import WebhookParser
from linebot.v3.messaging import (
    AsyncApiClient,
    AsyncMessagingApi,
    AsyncMessagingApiBlob,
    Configuration,
    ReplyMessageRequest,
    ShowLoadingAnimationRequest,
)

from app.core.config import LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET

parser = WebhookParser(LINE_CHANNEL_SECRET)
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)


def parse_events(body: str, signature: str) -> list:
    """เช็คลายเซ็นแล้วแกะ event · ลายเซ็นไม่ผ่าน → InvalidSignatureError"""
    return parser.parse(body, signature)


async def reply(reply_token: str, messages: list) -> None:
    async with AsyncApiClient(configuration) as api_client:
        await AsyncMessagingApi(api_client).reply_message(
            ReplyMessageRequest(reply_token=reply_token, messages=messages)
        )


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
