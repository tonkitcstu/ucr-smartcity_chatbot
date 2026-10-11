import base64
import hashlib
import hmac
import json

LINE_CHANNEL_SECRET = "test-secret"

# ตัวอย่างจากเอกสาร LINE Messaging API (Webhook Event Objects → Location, Sticker)
PIN = (35.67966, 139.73669)
PIN_TITLE = "my location"
PIN_ADDRESS = "1-3 Kioicho, Chiyoda-ku, Tokyo, 102-8282 Japan"
STICKER_KEYWORDS = [
    "cony", "sally", "Staring", "hi", "whatsup", "line", "howdy",
    "HEY", "Peeking", "wave", "peek", "Hello", "yo", "greetings",
]
MESSAGE_STICKER_KEYWORDS = ["Anticipation", "Sparkle", "Straight face", "Staring", "Thinking"]
MESSAGE_STICKER_TEXT = "Let's\nhang out\nthis weekend!"


def sign(body: str, secret: str = LINE_CHANNEL_SECRET) -> str:
    digest = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def webhook_body(*events: dict) -> str:
    return json.dumps({"destination": "Ubot", "events": list(events)})


def _event(kind: str, user_id: str, reply_token: str, event_id: str, **extra) -> dict:
    return {
        "type": kind,
        "mode": "active",
        "timestamp": 1760000000000,
        "source": {"type": "user", "userId": user_id},
        "replyToken": reply_token,
        "webhookEventId": event_id,
        "deliveryContext": {"isRedelivery": False},
        **extra,
    }


def follow_event(user_id="U_test", reply_token="rt-follow", event_id="ev-follow"):
    return _event("follow", user_id, reply_token, event_id, follow={"isUnblocked": False})


def postback_event(data, user_id="U_test", reply_token="rt-postback", event_id="ev-postback"):
    return _event("postback", user_id, reply_token, event_id, postback={"data": data})


def text_event(text, user_id="U_test", reply_token="rt-text", event_id="ev-text", message_id="m-1"):
    message = {"type": "text", "id": message_id, "text": text, "quoteToken": "q"}
    return _event("message", user_id, reply_token, event_id, message=message)


def image_event(user_id="U_test", reply_token="rt-image", event_id="ev-image", message_id="img-1"):
    message = {"type": "image", "id": message_id, "contentProvider": {"type": "line"}, "quoteToken": "q"}
    return _event("message", user_id, reply_token, event_id, message=message)


def location_event(
    latitude,
    longitude,
    user_id="U_test",
    reply_token="rt-location",
    event_id="ev-location",
    message_id="loc-1",
    title=None,
    address=None,
):
    """latitude, longitude มาเสมอ · title, address มาบางครั้ง (เอกสาร LINE)"""
    message = {"type": "location", "id": message_id, "markAsReadToken": "r", "latitude": latitude, "longitude": longitude}
    if title is not None:
        message["title"] = title
    if address is not None:
        message["address"] = address
    return _event("message", user_id, reply_token, event_id, message=message)


def sticker_event(
    keywords=None,
    text=None,
    user_id="U_test",
    reply_token="rt-sticker",
    event_id="ev-sticker",
    message_id="stk-1",
    resource_type="ANIMATION",
):
    """keywords มาบางครั้ง · text มีเฉพาะสติกเกอร์แบบพิมพ์ข้อความได้ (เอกสาร LINE)"""
    message = {
        "type": "sticker",
        "id": message_id,
        "quoteToken": "q",
        "markAsReadToken": "r",
        "stickerId": "52002738",
        "packageId": "11537",
        "stickerResourceType": resource_type,
    }
    if keywords is not None:
        message["keywords"] = keywords
    if text is not None:
        message["text"] = text
    return _event("message", user_id, reply_token, event_id, message=message)


def audio_event(user_id="U_test", reply_token="rt-audio", event_id="ev-audio", message_id="aud-1"):
    message = {"type": "audio", "id": message_id, "duration": 60000, "contentProvider": {"type": "line"}}
    return _event("message", user_id, reply_token, event_id, message=message)


async def post_webhook(client, *events, signature=None):
    body = webhook_body(*events)
    headers = {"X-Line-Signature": signature or sign(body), "Content-Type": "application/json"}
    return await client.post("/webhook/line", content=body, headers=headers)
