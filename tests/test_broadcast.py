# ทักไปก่อนเมื่อพยากรณ์บอกว่าฝนจะตก — อ่านพยากรณ์หลังตี 1 · ทักตั้งแต่ 8 โมง · เลย 2 ทุ่มไม่ทัก
# สุ่มวันละไม่เกิน BROADCAST_DAILY_LIMIT คน · แบบ docs/diagrams/broadcast-flow.mmd
# พยากรณ์ใช้ไฟล์ปลอม app/clients/mock_forecast.json (ฝนตกช่วง 14:00–15:00) · AI กับ LINE เป็นของปลอม

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

import httpx

from tests.line_webhook import follow_event, post_webhook, text_event, unfollow_event

THAI_TIME = timezone(timedelta(hours=7))
DAY = datetime(2026, 10, 23, tzinfo=THAI_TIME)
GREETING = ["สวัสดีค่ะ เมืองจากทีม UCR นะคะ วันนี้บ่าย ๆ อาจมีฝน", "ฝนตกทีไรแถวบ้านเป็นยังไงบ้างคะ ไม่สะดวกก็ไม่ต้องตอบนะคะ"]
REPLY = "ขอบคุณที่เล่าค่ะ น้ำท่วมสูงแค่ไหนคะ"
REASON = "พยากรณ์อากาศบอกว่าวันนี้อาจมีฝนแถวบ้าน"


def at(hour: int, minute: int = 0) -> datetime:
    return DAY.replace(hour=hour, minute=minute)


def chat_answer(texts: list[str]) -> str:
    return json.dumps({"texts": texts, "buttons": []}, ensure_ascii=False)


# แทน clients/ai.chat — รอบแรกตอบข้อความทัก รอบถัดไปตอบ REPLY · จดว่า AI เห็นอะไร
@pytest.fixture
def ai_chats(monkeypatch):
    from app.clients import ai
    from app.models.ai import AiReply

    calls = []

    async def fake_chat(model, messages, schema):
        calls.append([(m.role, m.content) for m in messages])
        texts = GREETING if len(calls) == 1 else [REPLY]
        return AiReply(text=chat_answer(texts), input_tokens=10, output_tokens=5)

    monkeypatch.setattr(ai, "chat", fake_chat)
    return calls


# แทน clients/line.push — จดว่าส่งหาใคร ข้อความอะไร ไม่ยิงไป LINE
@pytest.fixture
def pushes(monkeypatch):
    from app.clients import line

    calls = []

    async def fake_push(users, messages):
        calls.append((users.line_user_id, [message.text for message in messages]))

    monkeypatch.setattr(line, "push", fake_push)
    return calls


# แทน clients/line.monthly_messages_left — ค่าตั้งต้นไม่มีเพดาน · ข้อที่อยากลองเพดานใส่ค่าใน left[0]
@pytest.fixture(autouse=True)
def line_quota(monkeypatch):
    from app.clients import line

    left = [None]

    async def fake_monthly_messages_left():
        return left[0]

    monkeypatch.setattr(line, "monthly_messages_left", fake_monthly_messages_left)
    return left


# แทน clients/line.show_loading — worker เปิดจุดกำลังพิมพ์ก่อนตอบ
@pytest.fixture
def no_loading(monkeypatch):
    from app.clients import line

    async def fake_show_loading(line_user_id):
        pass

    monkeypatch.setattr(line, "show_loading", fake_show_loading)


async def add_user(db, line_user_id: str):
    return await db.fetchval(
        "INSERT INTO users (line_user_id, pdpa_accepted_at) VALUES ($1, now()) RETURNING user_id", line_user_id
    )


async def tick(now: datetime):
    from app.workers import broadcaster

    await broadcaster.tick(now)


async def broadcast_row(db):
    return await db.fetchrow("SELECT * FROM broadcasts WHERE forecast_date = $1", DAY.date())


async def broadcast_session(db, user_id):
    return await db.fetchrow("SELECT * FROM sessions WHERE user_id = $1 AND broadcast_id IS NOT NULL", user_id)


# ก่อนตี 1 ยังไม่อ่านพยากรณ์
async def test_nothing_before_one_am(client, db, ai_chats, pushes):
    await add_user(db, "U_a")

    await tick(at(0, 59))

    assert await broadcast_row(db) is None
    assert pushes == []


# หลังตี 1 อ่านพยากรณ์ ฝนจะตก → รอทัก · ยังไม่ถึง 8 โมงยังไม่ทัก
async def test_rain_is_scheduled_after_one_am(client, db, ai_chats, pushes):
    await add_user(db, "U_a")

    await tick(at(1, 0))

    row = await broadcast_row(db)
    assert row["status"] == "scheduled"
    assert row["reason"] == REASON
    assert pushes == []
    assert ai_chats == []


# ถึง 8 โมง → ตัวคุยแต่งข้อความทักจากเหตุที่ทัก · push หาผู้แจ้ง · ใบใหม่ติดป้าย broadcast · บันทึกข้อความและประวัติ
async def test_greets_everyone_at_eight(client, db, redis, ai_chats, pushes):
    user_id = await add_user(db, "U_a")
    await tick(at(1, 0))

    await tick(at(8, 0))

    assert pushes == [("U_a", GREETING)]
    [seen] = ai_chats
    assert seen[0][0] == "system"
    assert seen[1] == (
        "user",
        f"[ระบบ: เมืองทักผู้แจ้งไปก่อน ผู้แจ้งยังไม่ได้พิมพ์อะไร เหตุที่ทัก: {REASON}]",
    )

    opened = await broadcast_session(db, user_id)
    assert opened["status"] == "open"
    saved = await db.fetch(
        "SELECT role, content FROM messages WHERE session_id = $1 ORDER BY created_at", opened["session_id"]
    )
    assert [(row["role"], row["content"]) for row in saved] == [("assistant", text) for text in GREETING]
    history = [json.loads(item) for item in await redis.lrange(f"session:{opened['session_id']}:history", 0, -1)]
    assert [(item["role"], item["content"]) for item in history] == [seen[1], *[("assistant", t) for t in GREETING]]

    row = await broadcast_row(db)
    assert row["status"] == "sent"
    assert row["sent_at"] is not None


# ทักแล้ววันนั้นไม่ทักซ้ำ แม้ตัวทักตื่นมาอีกหลายรอบ
async def test_greets_only_once_a_day(client, db, ai_chats, pushes):
    await add_user(db, "U_a")
    await tick(at(8, 0))

    await tick(at(8, 1))
    await tick(at(12, 0))

    assert len(pushes) == 1


# แอปดับระหว่างทัก (ทักคนแรกแล้ว ยังไม่ถึงคนที่สอง) → แถวยังเป็น scheduled
# เปิดแอปใหม่ → ทักต่อเฉพาะคนที่ยังไม่ได้ ด้วยข้อความเดิมที่จดไว้ ไม่ให้ AI แต่งใหม่
# คนแรกไม่ถูกทักซ้ำ แม้เขาตอบจบจนใบถูกปิดไปแล้ว
async def test_resumes_after_shutdown_without_greeting_twice(client, db, ai_chats, pushes, monkeypatch):
    from app.services import broadcast

    await add_user(db, "U_a")
    await add_user(db, "U_b")
    real_open = broadcast.open_session_for
    opens = []

    async def shutdown_before_second(*args):
        opens.append(1)
        if len(opens) == 2:
            raise asyncio.CancelledError
        return await real_open(*args)

    monkeypatch.setattr(broadcast, "open_session_for", shutdown_before_second)
    with pytest.raises(asyncio.CancelledError):
        await tick(at(8, 0))
    [(first, _)] = pushes
    assert (await broadcast_row(db))["status"] == "scheduled"

    await db.execute(
        "UPDATE sessions SET status = 'closed', closed_at = now() "
        "WHERE user_id = (SELECT user_id FROM users WHERE line_user_id = $1)",
        first,
    )
    monkeypatch.setattr(broadcast, "open_session_for", real_open)
    await tick(at(8, 1))

    assert sorted(pushes) == [("U_a", GREETING), ("U_b", GREETING)]
    assert len(ai_chats) == 1
    assert (await broadcast_row(db))["status"] == "sent"


# AI แต่งข้อความทักครั้งเดียวต่อวัน · ทุกคนได้ข้อความเดียวกัน คนละใบ · ข้อความจดไว้ที่แถวของวันนั้น
async def test_everyone_gets_the_same_message_written_once(client, db, redis, ai_chats, pushes):
    first = await add_user(db, "U_a")
    second = await add_user(db, "U_b")

    await tick(at(8, 0))

    assert sorted(pushes) == [("U_a", GREETING), ("U_b", GREETING)]
    assert len(ai_chats) == 1
    assert json.loads((await broadcast_row(db))["greeting"])["texts"] == GREETING
    for user_id in (first, second):
        opened = await broadcast_session(db, user_id)
        saved = await db.fetch("SELECT content FROM messages WHERE session_id = $1 ORDER BY created_at", opened["session_id"])
        assert [row["content"] for row in saved] == GREETING
        history = [json.loads(item) for item in await redis.lrange(f"session:{opened['session_id']}:history", 0, -1)]
        assert history[0]["content"].startswith("[ระบบ: เมืองทักผู้แจ้งไปก่อน")
        assert [item["content"] for item in history[1:]] == GREETING


# งบ token ของตัวคุยทั้งระบบวันนี้หมด (#239) → ไม่ให้ AI แต่ง ไม่ทักใคร
async def test_token_limit_stops_before_writing(client, db, ai_chats, pushes, monkeypatch):
    from app.services import quota

    async def over_limit(*args):
        return True

    monkeypatch.setattr(quota, "is_over_system_daily_limit", over_limit)
    await add_user(db, "U_a")

    await tick(at(8, 0))

    assert ai_chats == []
    assert pushes == []


# ผู้แจ้งหลายคน → ทักทุกคน คนละใบ · คนที่กำลังคุยกับบอทอยู่ (มีใบเปิด) ข้าม
async def test_skips_whoever_is_talking(client, db, ai_chats, pushes):
    await add_user(db, "U_a")
    busy = await add_user(db, "U_busy")
    await add_user(db, "U_c")
    await db.execute("INSERT INTO sessions (user_id) VALUES ($1)", busy)

    await tick(at(8, 0))

    assert sorted(to for to, _ in pushes) == ["U_a", "U_c"]
    assert await broadcast_session(db, busy) is None


# ไม่มีฝน → ไม่ทักทั้งวัน
async def test_no_rain_no_greeting(client, db, ai_chats, pushes, monkeypatch):
    from app.clients import weather

    real_fetch = weather.fetch_daily

    async def dry_day(day):
        forecast = await real_fetch(day)
        for community in forecast["WeatherForecasts"]:
            for hour in community["forecasts"]:
                hour["condition_label"], hour["rainfall"] = "แจ่มใส", 0
        return forecast

    monkeypatch.setattr(weather, "fetch_daily", dry_day)
    await add_user(db, "U_a")

    await tick(at(1, 0))
    await tick(at(8, 0))

    row = await broadcast_row(db)
    assert (row["status"], row["reason"]) == ("skipped", None)
    assert pushes == []
    assert ai_chats == []


# แอปดับไปทั้งวัน เปิดอีกทีตอน 2 ทุ่ม → ไม่ทักแล้ว ไม่ส่งข้อความตอนดึก
async def test_too_late_is_expired(client, db, ai_chats, pushes):
    await add_user(db, "U_a")

    await tick(at(20, 0))

    assert (await broadcast_row(db))["status"] == "expired"
    assert pushes == []


# AI ทักคนแรกไม่ผ่าน → ข้ามไปคนถัดไป วันนั้นยังนับว่าทักแล้ว
async def test_one_failure_does_not_stop_the_rest(client, db, pushes, monkeypatch):
    from app.clients import ai
    from app.models.ai import AiReply

    answers = ["ไม่ใช่ JSON", chat_answer(GREETING)]

    async def fake_chat(model, messages, schema):
        return AiReply(text=answers.pop(0), input_tokens=10, output_tokens=5)

    monkeypatch.setattr(ai, "chat", fake_chat)
    await add_user(db, "U_a")
    await add_user(db, "U_b")

    await tick(at(8, 0))

    assert [message for _, message in pushes] == [GREETING]
    assert (await broadcast_row(db))["status"] == "sent"


# ผู้แจ้งตอบกลับ → เข้าใบเดิมที่บอททัก · ตัวคุยเห็นว่าตัวเองทักไปเพราะอะไร และทักว่าอะไร
async def test_reply_continues_the_greeting(client, db, redis, ai_chats, pushes, replies, no_loading):
    from app.models.job import Job
    from app.workers import worker

    user_id = await add_user(db, "U_a")
    await tick(at(8, 0))
    opened = await broadcast_session(db, user_id)

    await post_webhook(client, text_event("ฝนตกทีไรน้ำท่วมหน้าบ้านค่ะ", user_id="U_a"))
    await worker.run_chat(Job.model_validate_json(await redis.lpop("jobs")))

    assert await db.fetchval("SELECT count(*) FROM sessions WHERE user_id = $1", user_id) == 1
    second = ai_chats[1]
    assert second[1][1].startswith("[ระบบ: เมืองทักผู้แจ้งไปก่อน")
    assert second[2:4] == [("assistant", text) for text in GREETING]
    assert second[4] == ("user", "ฝนตกทีไรน้ำท่วมหน้าบ้านค่ะ")
    assert [message.text for message in replies[0][1]] == [REPLY]
    assert await db.fetchval("SELECT session_id FROM messages WHERE role = 'user'") == opened["session_id"]


# ใบที่บอททักแล้วผู้แจ้งยังไม่ตอบ เงียบ 10 นาทียังไม่ปิด · รอได้ถึง 24 ชั่วโมง
# ปิดแล้วไม่เรียกตัววิเคราะห์ เพราะผู้แจ้งไม่ได้พูดอะไร
async def test_unanswered_greeting_waits_then_closes_without_analysis(client, db, redis, ai_chats, pushes):
    from app.models.job import Job
    from app.workers import sweeper, worker

    user_id = await add_user(db, "U_a")
    await tick(at(8, 0))
    session_id = (await broadcast_session(db, user_id))["session_id"]

    await db.execute("UPDATE sessions SET last_message_at = now() - interval '11 minutes' WHERE session_id = $1", session_id)
    await sweeper.sweep()
    assert await db.fetchval("SELECT status FROM sessions WHERE session_id = $1", session_id) == "open"

    await db.execute("UPDATE sessions SET last_message_at = now() - interval '23 hours' WHERE session_id = $1", session_id)
    await sweeper.sweep()
    assert await db.fetchval("SELECT status FROM sessions WHERE session_id = $1", session_id) == "open"

    await db.execute("UPDATE sessions SET last_message_at = now() - interval '25 hours' WHERE session_id = $1", session_id)
    await sweeper.sweep()
    assert await db.fetchval("SELECT status FROM sessions WHERE session_id = $1", session_id) == "closed"

    await worker.run_analyse(Job.model_validate_json(await redis.lpop("jobs")))
    assert await db.fetchval("SELECT status FROM sessions WHERE session_id = $1", session_id) == "analysed"
    assert await db.fetchval("SELECT count(*) FROM ai_calls WHERE kind = 'analyser'") == 0


# --- พยากรณ์จริง (#252): นับเฉพาะฝนในชั่วโมงที่ทักได้ · ร้อนอย่างเดียวไม่นับ · ชุมชนที่ดึงพยากรณ์ไม่ได้ข้าม ---


def hour(clock: str, label: str = "มีเมฆมากขึ้น", rainfall: float = 0, temperature: float = 30.0) -> dict:
    return {
        "time": f"2026-10-23T{clock}:00+07:00",
        "temperature": temperature,
        "humidity": 70.0,
        "rainfall": rainfall,
        "condition": 4,
        "condition_label": label,
        "wind_speed": 2.0,
        "wind_direction": 180.0,
    }


def forecast_of(*communities: dict) -> dict:
    return {"date": "2026-10-23", "WeatherForecasts": list(communities)}


def community(*hours: dict) -> dict:
    return {"name": "ชุมชนตัวอย่าง", "location": {}, "forecasts": list(hours), "source": "tmd"}


@pytest.fixture
def forecast(monkeypatch):
    """ใส่พยากรณ์ที่อยากลองใน forecast[0]"""
    from app.clients import weather

    given = [None]

    async def fake_fetch_daily(day):
        return given[0]

    monkeypatch.setattr(weather, "fetch_daily", fake_fetch_daily)
    return given


async def test_rain_at_night_is_not_a_reason(client, db, forecast):
    forecast[0] = forecast_of(community(hour("02:00", "มีฝน", 1.2), hour("21:00", "ฝนฟ้าคะนอง", 3.0)))

    await tick(at(1, 0))

    row = await broadcast_row(db)
    assert (row["status"], row["reason"]) == ("skipped", None)


async def test_heat_without_rain_is_not_a_reason(client, db, forecast):
    forecast[0] = forecast_of(community(hour("12:00", temperature=36.2), hour("13:00", temperature=37.0)))

    await tick(at(1, 0))

    row = await broadcast_row(db)
    assert (row["status"], row["reason"]) == ("skipped", None)


async def test_community_without_forecast_is_skipped(client, db, forecast):
    failed = {"error": "TMD: 500 | Open-Meteo: 429", "name": "ชุมชนที่ดึงไม่ได้", "type": "latlon"}
    forecast[0] = forecast_of(failed, community(hour("14:00", "มีฝน", 2.0)))

    await tick(at(1, 0))

    row = await broadcast_row(db)
    assert (row["status"], row["reason"]) == ("scheduled", REASON)


async def test_reads_the_daily_file_from_forecast_url(client, db, monkeypatch):
    from app.clients import weather

    asked = []

    async def fake_get(self, url):
        asked.append(url)
        body = forecast_of(community(hour("14:00", "มีฝน", 2.0)))
        return httpx.Response(200, json=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(weather, "FORECAST_URL", "https://forecast.test/forecast/{date}.json")
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    await tick(at(1, 0))

    assert asked == ["https://forecast.test/forecast/2026-10-23.json"]
    assert (await broadcast_row(db))["status"] == "scheduled"


async def test_file_not_uploaded_yet_tries_again_later(client, db, monkeypatch):
    from app.clients import weather

    async def not_uploaded(self, url):
        return httpx.Response(403, request=httpx.Request("GET", url))

    monkeypatch.setattr(weather, "FORECAST_URL", "https://forecast.test/forecast/{date}.json")
    monkeypatch.setattr(httpx.AsyncClient, "get", not_uploaded)

    with pytest.raises(httpx.HTTPStatusError):
        await tick(at(1, 0))

    assert await broadcast_row(db) is None


# --- ใครได้ข้อความ: สุ่มวันละไม่เกิน BROADCAST_DAILY_LIMIT คน · ไม่เกินข้อความที่เหลือของเดือนใน LINE ---


@pytest.fixture
def daily_limit(monkeypatch):
    from app.services import broadcast

    def set_limit(count: int):
        monkeypatch.setattr(broadcast, "BROADCAST_DAILY_LIMIT", count)

    return set_limit


async def test_no_more_than_the_daily_limit(client, db, ai_chats, pushes, daily_limit):
    daily_limit(2)
    for line_user_id in ("U_a", "U_b", "U_c"):
        await add_user(db, line_user_id)

    await tick(at(8, 0))

    picked = [to for to, _ in pushes]
    assert len(picked) == len(set(picked)) == 2
    assert (await broadcast_row(db))["status"] == "sent"


async def test_resume_sends_only_what_is_left_of_the_daily_limit(client, db, ai_chats, pushes, daily_limit):
    daily_limit(1)
    await add_user(db, "U_a")
    await add_user(db, "U_b")
    await tick(at(8, 0))
    # แอปดับหลังทักครบแต่ก่อนจดว่า sent
    await db.execute("UPDATE broadcasts SET status = 'scheduled', sent_at = NULL")

    await tick(at(8, 1))

    assert len(pushes) == 1


async def test_no_more_than_line_messages_left_this_month(client, db, ai_chats, pushes, line_quota):
    line_quota[0] = 1
    await add_user(db, "U_a")
    await add_user(db, "U_b")

    await tick(at(8, 0))

    assert len(pushes) == 1


async def test_no_line_messages_left_sends_nothing(client, db, ai_chats, pushes, line_quota):
    line_quota[0] = 0
    await add_user(db, "U_a")

    await tick(at(8, 0))

    assert pushes == []
    assert ai_chats == []


async def test_blocked_bot_gets_nothing_until_follow_again(client, db, ai_chats, pushes):
    user_id = await add_user(db, "U_a")

    await post_webhook(client, unfollow_event(user_id="U_a"))
    assert await db.fetchval("SELECT blocked_at FROM users WHERE user_id = $1", user_id) is not None
    await tick(at(8, 0))
    assert pushes == []

    await post_webhook(client, follow_event(user_id="U_a"))
    assert await db.fetchval("SELECT blocked_at FROM users WHERE user_id = $1", user_id) is None


async def test_unfollow_before_pdpa_keeps_nothing(client, db):
    response = await post_webhook(client, unfollow_event(user_id="U_stranger"))

    assert response.status_code == 200
    assert await db.fetchval("SELECT count(*) FROM users") == 0
