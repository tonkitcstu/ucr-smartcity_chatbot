"""H12 ท่อส่ง push message — milestone 2.0.1 ข้อ 3 · spec ใน #235 · แบบ docs/designs/09-modules/h12-push.puml"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from linebot.v3.messaging import TextMessage, async_rest

# ที่อยู่ของ LINE ตามเอกสาร Messaging API (เปิดดู 2026-10-13) — เทียบแค่ส่วนท้าย
PUSH = "/v2/bot/message/push"
MULTICAST = "/v2/bot/message/multicast"
REPLY = "/v2/bot/message/reply"
# LINE รับ multicast ได้สูงสุดกี่คนต่อคำขอ
MULTICAST_MAX = 500

# คำตอบที่ AI แต่งตอนลองยิงจริง 2026-10-13 — ชุดเดียวกับ H11
FEEL = "แย่จังเลยนะคะ น้ำท่วมถึงเข่าแล้วลูกไปโรงเรียนลำบากด้วย"
ASK_WHERE = "จุดนี้น้ำท่วมตรงแถวไหนหรือคะ แชร์ตำแหน่งให้เมืองหน่อยนะคะ หรือจะบอกเป็นคำพูดก็ได้ค่ะ"
SHARE_LOCATION = "แชร์ตำแหน่ง"


class LineOk:
    """คำตอบ 200 ของ LINE เท่าที่ SDK อ่าน"""

    status = 200
    reason = "OK"
    headers = {"content-type": "application/json"}


@pytest.fixture(autouse=True)
def line_requests(monkeypatch):
    """แทนชั้น HTTP ของ SDK — จดคำขอที่กำลังจะออกไปหา LINE (method · ที่อยู่ · body) ไม่ยิงจริง
    คำขอประกอบด้วยโค้ดตัวจริงของ clients/line กับ SDK · autouse: ไม่มีข้อไหนในไฟล์นี้ยิงออกได้"""
    calls = []

    async def fake_request(
        self, method, url, query_params=None, headers=None, body=None, post_params=None,
        _preload_content=True, _request_timeout=None,
    ):
        calls.append((method, url, body))
        # multicast ตอบ {} · push กับ reply ตอบรายการข้อความที่ส่ง (ตัวอย่างในเอกสาร)
        data = b"{}" if url.endswith(MULTICAST) else b'{"sentMessages": [{"id": "461230966842064897"}]}'
        return async_rest.RESTResponse(LineOk(), data)

    monkeypatch.setattr(async_rest.RESTClientObject, "request", fake_request)
    return calls


def make_user(number: int):
    """ผู้แจ้งที่ยอมรับ PDPA แล้ว · LINE user ID หน้าตาแบบของจริง: U ตามด้วยเลขฐานสิบหก 32 ตัว"""
    from app.models.user import User

    return User(user_id=uuid4(), line_user_id=f"U{number:032x}", pdpa_accepted_at=datetime.now(UTC))


def texts_with_button() -> list:
    """ข้อความชุดที่ worker ส่งตอนตอบ (H11): สองข้อความ ปุ่ม location ใต้ข้อความสุดท้าย"""
    from app.clients import line
    from app.models.line import QuickReplyButton

    quick_reply = line.build_quick_reply([QuickReplyButton(type="location", label=SHARE_LOCATION)])
    return [TextMessage(text=FEEL), TextMessage(text=ASK_WHERE, quick_reply=quick_reply)]


def pdpa_card() -> list:
    """การ์ด PDPA ที่ controller ส่งตอนเพิ่มเพื่อน (H1)"""
    from app.services import pdpa

    return [pdpa.card()]


async def test_one_user_goes_out_as_one_push_request(line_requests):
    from app.clients import line

    user = make_user(1)

    await line.push(user, [TextMessage(text=FEEL)])

    assert len(line_requests) == 1
    method, url, body = line_requests[0]
    assert method == "POST"
    assert url.endswith(PUSH)
    assert body["to"] == user.line_user_id
    assert body["messages"] == [{"type": "text", "text": FEEL}]


@pytest.mark.parametrize("build", [texts_with_button, pdpa_card])
async def test_push_sends_the_same_messages_as_reply(line_requests, build):
    """push ใช้ได้กับข้อความทุกชนิดที่ reply ส่ง — ข้อความ · ปุ่มใต้ข้อความ · การ์ด"""
    from app.clients import line

    await line.reply("reply-token", build())
    await line.push(make_user(1), build())

    (_, reply_url, reply_body), (_, push_url, push_body) = line_requests
    assert reply_url.endswith(REPLY)
    assert push_url.endswith(PUSH)
    assert push_body["messages"]
    assert push_body["messages"] == reply_body["messages"]


async def test_several_users_go_out_as_one_multicast_request(line_requests):
    from app.clients import line

    users = [make_user(number) for number in (1, 2, 3)]

    await line.push(users, [TextMessage(text=FEEL)])

    assert len(line_requests) == 1
    method, url, body = line_requests[0]
    assert method == "POST"
    assert url.endswith(MULTICAST)
    assert body["to"] == [user.line_user_id for user in users]
    assert body["messages"] == [{"type": "text", "text": FEEL}]


async def test_list_of_one_user_goes_out_as_push(line_requests):
    """LINE แนะนำ push เมื่อผู้รับมีคนเดียว"""
    from app.clients import line

    user = make_user(1)

    await line.push([user], [TextMessage(text=FEEL)])

    assert len(line_requests) == 1
    _, url, body = line_requests[0]
    assert url.endswith(PUSH)
    assert body["to"] == user.line_user_id


async def test_more_than_five_hundred_users_go_out_in_groups(line_requests):
    from app.clients import line

    users = [make_user(number) for number in range(1, MULTICAST_MAX + 2)]

    await line.push(users, [TextMessage(text=FEEL)])

    assert [url.endswith(MULTICAST) for _, url, _ in line_requests] == [True, True]
    first, second = (body for _, _, body in line_requests)
    assert [len(first["to"]), len(second["to"])] == [MULTICAST_MAX, 1]
    assert first["to"] + second["to"] == [user.line_user_id for user in users]
    assert first["messages"] == second["messages"] == [{"type": "text", "text": FEEL}]


async def test_no_users_sends_nothing(line_requests):
    from app.clients import line

    await line.push([], [TextMessage(text=FEEL)])

    assert line_requests == []
