import base64
import hashlib
import hmac
import json

LINE_CHANNEL_SECRET = "test-secret"


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


async def post_webhook(client, *events, signature=None):
    body = webhook_body(*events)
    headers = {"X-Line-Signature": signature or sign(body), "Content-Type": "application/json"}
    return await client.post("/webhook/line", content=body, headers=headers)
