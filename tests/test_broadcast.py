# ทักไปก่อนเมื่อพยากรณ์บอกว่าฝนจะตก — อ่านพยากรณ์หลังตี 1 · ทักตั้งแต่ 8 โมง · เลย 2 ทุ่มไม่ทัก
# พยากรณ์ใช้ไฟล์ปลอม app/clients/mock_forecast.json (ฝนตกช่วง 14:00–15:00) · AI กับ LINE เป็นของปลอม

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from tests.line_webhook import post_webhook, text_event

THAI_TIME = timezone(timedelta(hours=7))
DAY = datetime(2026, 10, 23, tzinfo=THAI_TIME)
GREETING = ["สวัสดีค่ะ เมืองจากทีม UCR นะคะ วันนี้บ่าย ๆ อาจมีฝน", "ฝนตกทีไรแถวบ้านเป็นยังไงบ้างคะ ไม่สะดวกก็ไม่ต้องตอบนะคะ"]
REPLY = "ขอบคุณที่เล่าค่ะ น้ำท่วมสูงแค่ไหนคะ"


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
    assert row["reason"] == "พยากรณ์อากาศบอกว่าวันนี้อาจมีฝนช่วง 14:00 ถึง 15:00 น."
    assert json.loads(row["forecast"])["date"] == "2026-10-23"
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
        "[ระบบ: เมืองทักผู้แจ้งไปก่อน ผู้แจ้งยังไม่ได้พิมพ์อะไร เหตุที่ทัก: "
        "พยากรณ์อากาศบอกว่าวันนี้อาจมีฝนช่วง 14:00 ถึง 15:00 น.]",
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
# เปิดแอปใหม่ → ทักต่อเฉพาะคนที่ยังไม่ได้ · คนแรกไม่ถูกทักซ้ำ แม้เขาตอบจบจนใบถูกปิดไปแล้ว
async def test_resumes_after_shutdown_without_greeting_twice(client, db, ai_chats, pushes, monkeypatch):
    from app.services import quota

    first = await add_user(db, "U_a")
    await add_user(db, "U_b")
    real_check = quota.is_over_system_daily_limit
    checks = []

    async def shutdown_before_second(*args):
        checks.append(1)
        if len(checks) == 2:
            raise asyncio.CancelledError
        return await real_check(*args)

    monkeypatch.setattr(quota, "is_over_system_daily_limit", shutdown_before_second)
    with pytest.raises(asyncio.CancelledError):
        await tick(at(8, 0))
    assert [to for to, _ in pushes] == ["U_a"]
    assert (await broadcast_row(db))["status"] == "scheduled"

    await db.execute("UPDATE sessions SET status = 'closed', closed_at = now() WHERE user_id = $1", first)
    monkeypatch.setattr(quota, "is_over_system_daily_limit", real_check)
    await tick(at(8, 1))

    assert [to for to, _ in pushes] == ["U_a", "U_b"]
    assert (await broadcast_row(db))["status"] == "sent"


# ผู้แจ้งหลายคน → ทักทุกคน คนละใบ · คนที่กำลังคุยกับบอทอยู่ (มีใบเปิด) ข้าม
async def test_skips_whoever_is_talking(client, db, ai_chats, pushes):
    await add_user(db, "U_a")
    busy = await add_user(db, "U_busy")
    await add_user(db, "U_c")
    await db.execute("INSERT INTO sessions (user_id) VALUES ($1)", busy)

    await tick(at(8, 0))

    assert [to for to, _ in pushes] == ["U_a", "U_c"]
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

    assert pushes == [("U_b", GREETING)]
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


# ใบที่บอททักแล้วผู้แจ้งยังไม่ตอบ เงียบ 10 นาทียังไม่ปิด · รอได้ถึง 12 ชั่วโมง
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

    await db.execute("UPDATE sessions SET last_message_at = now() - interval '13 hours' WHERE session_id = $1", session_id)
    await sweeper.sweep()
    assert await db.fetchval("SELECT status FROM sessions WHERE session_id = $1", session_id) == "closed"

    await worker.run_analyse(Job.model_validate_json(await redis.lpop("jobs")))
    assert await db.fetchval("SELECT status FROM sessions WHERE session_id = $1", session_id) == "analysed"
    assert await db.fetchval("SELECT count(*) FROM ai_calls WHERE kind = 'analyser'") == 0
