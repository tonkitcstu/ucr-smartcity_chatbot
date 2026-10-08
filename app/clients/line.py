"""ภาษาของ LINE: ลายเซ็น, แกะ event, reply"""

from linebot.v3 import WebhookParser
from linebot.v3.messaging import (
    AsyncApiClient,
    AsyncMessagingApi,
    Configuration,
    ReplyMessageRequest,
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
