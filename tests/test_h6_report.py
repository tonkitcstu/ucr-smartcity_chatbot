"""H6 Worker ทำรายงาน — S4 S7 · spec ใน #154 · แบบ docs/designs/09-modules/h6-report.puml"""

import json
from itertools import product
from types import SimpleNamespace

import pytest

CHAT_PROMPT = "คุณคือน้องเมือง"
CHAT_MODEL = "test-chat-model"
ANALYSER_PROMPT = "สรุปเรื่องที่ผู้แจ้งเล่าเป็นรายงาน"
ANALYSER_MODEL = "test-analyser-model"


@pytest.fixture
async def ai_config(db):
    """ai_configs 1 ชุด — ตัวคุยกับตัววิเคราะห์ใช้ model / prompt คนละตัว"""
    chat_model = await db.fetchval(
        "INSERT INTO models (provider, name) VALUES ('test', $1) RETURNING model_id", CHAT_MODEL
    )
    analyser_model = await db.fetchval(
        "INSERT INTO models (provider, name) VALUES ('test', $1) RETURNING model_id", ANALYSER_MODEL
    )
    chat_prompt = await db.fetchval("INSERT INTO prompts (prompt) VALUES ($1) RETURNING prompt_id", CHAT_PROMPT)
    analyser_prompt = await db.fetchval(
        "INSERT INTO prompts (prompt) VALUES ($1) RETURNING prompt_id", ANALYSER_PROMPT
    )
    return await db.fetchval(
        """
        INSERT INTO ai_configs (chat_model_id, chat_prompt_id, analyzer_model_id, analyzer_prompt_id)
        VALUES ($1, $2, $3, $4) RETURNING ai_config_id
        """,
        chat_model,
        chat_prompt,
        analyser_model,
        analyser_prompt,
    )


@pytest.fixture
def analyser_ai(monkeypatch):
    """แทน clients/ai.structured — คืนคำตอบตามลำดับใน replies · จดว่าได้ model, messages, schema อะไร"""
    from app.clients import ai
    from app.models.ai import AiReply

    fake = SimpleNamespace(replies=[], calls=[])

    async def fake_structured(model, messages, schema):
        fake.calls.append((model, messages, schema))
        return AiReply(text=fake.replies.pop(0), input_tokens=20, output_tokens=8)

    monkeypatch.setattr(ai, "structured", fake_structured, raising=False)
    return fake


@pytest.fixture
def chats(monkeypatch):
    """แทน clients/ai.chat — จดว่าถูกเรียกไหม (งานวิเคราะห์ต้องไม่เรียกตัวคุย)"""
    from app.clients import ai

    calls = []

    async def fake_chat(model, messages):
        calls.append((model, messages))

    monkeypatch.setattr(ai, "chat", fake_chat)
    return calls


def answer(*reports):
    """คำตอบของ AI ตามรูปแบบ Analysis"""
    return json.dumps({"reports": list(reports)}, ensure_ascii=False)


async def closed_session(db, *items):
    """ใบที่ sweeper ปิดแล้ว · บทสนทนาตามลำดับ items · คืน (session_id, attachment_id ของรูปตามลำดับ)

    item: ("user" | "assistant", "text", ข้อความ) · ("user", "image", file_path) · ("user", "location", (lat, lng))
    """
    user_id = await db.fetchval(
        "INSERT INTO users (line_user_id, pdpa_accepted_at) VALUES ('U_a', now()) RETURNING user_id"
    )
    session_id = await db.fetchval(
        """
        INSERT INTO sessions (user_id, status, started_at, last_message_at, closed_at)
        VALUES ($1, 'closed', now() - interval '30 minutes', now() - interval '11 minutes', now())
        RETURNING session_id
        """,
        user_id,
    )
    attachment_ids = []
    for order, (role, kind, value) in enumerate(items):
        content = value if kind == "text" else None
        lat, lng = value if kind == "location" else (None, None)
        message_id = await db.fetchval(
            """
            INSERT INTO messages (session_id, role, type, content, lat, lng, status, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, 'answered', now() - interval '30 minutes' + make_interval(secs => $7))
            RETURNING message_id
            """,
            session_id,
            role,
            kind,
            content,
            lat,
            lng,
            order,
        )
        if kind == "image":
            attachment_ids.append(
                await db.fetchval(
                    "INSERT INTO attachments (message_id, type, file_path) VALUES ($1, 'image', $2) RETURNING attachment_id",
                    message_id,
                    value,
                )
            )
    return session_id, attachment_ids


async def run_analyse(session_id):
    from app.models.job import Job
    from app.workers import worker

    await worker.run_analyse(Job(kind="analyse", session_id=session_id))


def sent_to_ai(call):
    _, messages, _ = call
    return [(m.role, m.type, m.content) for m in messages]


async def reports_of(db, session_id):
    return await db.fetch("SELECT * FROM reports WHERE session_id = $1 ORDER BY created_at, report_id", session_id)


async def report_of_attachment(db, attachment_id):
    return await db.fetchval("SELECT report_id FROM attachments WHERE attachment_id = $1", attachment_id)


async def status_of(db, session_id):
    return await db.fetchval("SELECT status FROM sessions WHERE session_id = $1", session_id)


# 1. สถานการณ์หลัก


async def test_text_image_location_become_one_report(client, db, ai_config, analyser_ai):
    """1. เล่าข้อความ + รูป + ตำแหน่ง → AI ได้บทสนทนาครบพร้อมป้าย · รายงาน 1 ใบมีสรุป tag พิกัด · รูปผูกรายงาน · analysed"""
    from app.models.report import Analysis

    session_id, [photo] = await closed_session(
        db,
        ("user", "text", "น้ำท่วมหน้าบ้าน"),
        ("assistant", "text", "น้ำสูงแค่ไหนครับ"),
        ("user", "image", "/uploads/photo.jpg"),
        ("user", "location", (13.75, 100.5)),
        ("user", "text", "สูงประมาณเข่า"),
    )
    reply = answer({"desc": "น้ำท่วมหน้าบ้าน สูงประมาณเข่า", "tags": ["น้ำท่วม"], "location": 1, "images": [1]})
    analyser_ai.replies = [reply]

    await run_analyse(session_id)

    assert len(analyser_ai.calls) == 1
    model, _, schema = analyser_ai.calls[0]
    assert model == ANALYSER_MODEL
    assert schema is Analysis
    assert sent_to_ai(analyser_ai.calls[0]) == [
        ("system", "text", ANALYSER_PROMPT),
        ("user", "text", "น้ำท่วมหน้าบ้าน"),
        ("assistant", "text", "น้ำสูงแค่ไหนครับ"),
        ("user", "text", "[รูป 1]"),
        ("user", "image", "/uploads/photo.jpg"),
        ("user", "text", "[ตำแหน่ง 1]"),
        ("user", "text", "สูงประมาณเข่า"),
    ]

    [report] = await reports_of(db, session_id)
    assert report["desc"] == "น้ำท่วมหน้าบ้าน สูงประมาณเข่า"
    assert report["tags"] == ["น้ำท่วม"]
    assert (report["lat"], report["lng"]) == (13.75, 100.5)
    assert report["ai_config_id"] == ai_config
    assert report["started_at"] == await db.fetchval(
        "SELECT started_at FROM sessions WHERE session_id = $1", session_id
    )
    assert await report_of_attachment(db, photo) == report["report_id"]

    ai_call = await db.fetchrow("SELECT * FROM ai_calls")
    assert ai_call["session_id"] == session_id
    assert ai_call["ai_config_id"] == ai_config
    assert ai_call["kind"] == "analyser"
    assert ai_call["status"] == "ok"
    assert ai_call["response"] == reply
    assert ai_call["input_tokens"] == 20
    assert ai_call["output_tokens"] == 8

    assert await status_of(db, session_id) == "analysed"


# A. AI ตอบถูกรูปแบบ — แต่ละรายงานมีรูปไหม (T/F) มีตำแหน่งไหม (T/F)

ONE_REPORT = [[shape] for shape in product([False, True], repeat=2)]
TWO_REPORTS = [[(a, b), (c, d)] for a, b, c, d in product([False, True], repeat=4)]


def shape_id(shapes):
    """[(รูป, ตำแหน่ง), ...] → "TF-FT" """
    return "-".join("".join("T" if flag else "F" for flag in shape) for shape in shapes)


async def session_for(db, shapes):
    """เรื่องละ 1 ข้อความ · มีรูป → ตามด้วยรูป · มีตำแหน่ง → ตามด้วยตำแหน่ง
    คืน session_id กับรายงานที่คาดไว้ [(desc, รูปของเรื่อง | None, (lat, lng) | None)]
    และคำตอบ AI ที่อ้างเลขป้ายตามลำดับในบทสนทนา"""
    items, stories = [], []
    for number, (has_image, has_location) in enumerate(shapes, start=1):
        items.append(("user", "text", f"เรื่องที่ {number}"))
        if has_image:
            items.append(("user", "image", f"/uploads/{number}.jpg"))
        if has_location:
            items.append(("user", "location", (13.0 + number, 100.0 + number)))
        stories.append((f"เรื่องที่ {number}", has_image, (13.0 + number, 100.0 + number) if has_location else None))
    session_id, attachment_ids = await closed_session(db, *items)

    drafts, expected, image_label, location_label = [], [], 0, 0
    photos = iter(attachment_ids)
    for desc, has_image, pin in stories:
        image = next(photos) if has_image else None
        image_label += has_image
        location_label += pin is not None
        drafts.append(
            {
                "desc": desc,
                "tags": [f"tag-{desc}"],
                "location": location_label if pin else None,
                "images": [image_label] if has_image else [],
            }
        )
        expected.append((desc, image, pin))
    return session_id, expected, answer(*drafts)


@pytest.mark.parametrize("shapes", ONE_REPORT + TWO_REPORTS, ids=shape_id)
async def test_each_report_gets_its_own_image_and_pin(client, db, ai_config, analyser_ai, shapes):
    """A1 รายงาน 1 ใบ 4 แบบ · A2 รายงาน 2 ใบ 16 แบบ → แต่ละใบได้พิกัดและรูปของตัวเอง · มีอันไหนไม่มี → ว่าง"""
    session_id, expected, reply = await session_for(db, shapes)
    analyser_ai.replies = [reply]

    await run_analyse(session_id)

    reports = {row["desc"]: row for row in await reports_of(db, session_id)}
    assert set(reports) == {desc for desc, _, _ in expected}
    for desc, image, pin in expected:
        report = reports[desc]
        assert report["tags"] == [f"tag-{desc}"]
        assert (report["lat"], report["lng"]) == (pin or (None, None))
        linked = await db.fetch("SELECT attachment_id FROM attachments WHERE report_id = $1", report["report_id"])
        assert [row["attachment_id"] for row in linked] == ([image] if image else [])
    assert await status_of(db, session_id) == "analysed"


async def test_dispute_between_people_makes_no_report(client, db, ai_config, analyser_ai):
    """A3 เรื่องพิพาทระหว่างคน → AI ตอบ reports ว่าง · ไม่มีรายงาน · รูปไม่ผูก · ใบยัง analysed [S7]"""
    session_id, [photo] = await closed_session(
        db,
        ("user", "text", "บ้านข้าง ๆ จอดรถขวางหน้าบ้านทุกวัน"),
        ("user", "image", "/uploads/car.jpg"),
    )
    analyser_ai.replies = [answer()]

    await run_analyse(session_id)

    assert await reports_of(db, session_id) == []
    assert await report_of_attachment(db, photo) is None
    assert await db.fetchval("SELECT status FROM ai_calls") == "ok"
    assert await status_of(db, session_id) == "analysed"


# B. AI ตอบผิดรูปแบบ — แกะไม่ผ่าน → ai_calls error · ลองใหม่ด้วยบทสนทนาชุดเดิม

RIGHT = answer({"desc": "ขยะล้นถังหน้าตลาด", "tags": ["ขยะ"], "location": None, "images": []})
REPORT = {"desc": "ขยะล้นถัง", "tags": ["ขยะ"], "location": None, "images": []}
WRONG = {
    "B1-not-json": "ขอโทษครับ ผมสรุปไม่ได้",
    "B2-cut-off": '{"reports": [{"desc": "ขยะล้น',
    "B3-no-reports": json.dumps({"report": [REPORT]}),
    "B4-reports-not-list": json.dumps({"reports": REPORT}),
    "B5-no-desc": json.dumps({"reports": [{k: v for k, v in REPORT.items() if k != "desc"}]}),
    "B6-tags-not-list": json.dumps({"reports": [{**REPORT, "tags": "ขยะ"}]}),
    "B7-no-location-key": json.dumps({"reports": [{k: v for k, v in REPORT.items() if k != "location"}]}),
    "B8-location-is-word": json.dumps({"reports": [{**REPORT, "location": "หน้าบ้าน"}]}),
    "B9-images-not-numbers": json.dumps({"reports": [{**REPORT, "images": ["photo.jpg"]}]}),
}


@pytest.mark.parametrize("wrong", WRONG.values(), ids=WRONG.keys())
async def test_wrong_format_then_right_format(client, db, ai_config, analyser_ai, wrong):
    """B1–B9 ครั้งแรกผิดรูปแบบ ครั้งที่สองถูก → ai_calls (error, ok) · error มีเหตุ · ส่งชุดเดิม · รายงานจากครั้งที่สอง"""
    session_id, _ = await closed_session(db, ("user", "text", "ขยะล้นถังหน้าตลาด"))
    analyser_ai.replies = [wrong, RIGHT]

    await run_analyse(session_id)

    assert len(analyser_ai.calls) == 2
    assert sent_to_ai(analyser_ai.calls[0]) == sent_to_ai(analyser_ai.calls[1])

    rows = await db.fetch("SELECT kind, status, response, error FROM ai_calls ORDER BY created_at")
    assert [(row["kind"], row["status"]) for row in rows] == [("analyser", "error"), ("analyser", "ok")]
    assert rows[0]["response"] == wrong
    assert rows[0]["error"]
    assert rows[1]["response"] == RIGHT
    assert rows[1]["error"] is None

    [report] = await reports_of(db, session_id)
    assert report["desc"] == "ขยะล้นถังหน้าตลาด"
    assert await status_of(db, session_id) == "analysed"


# D. งานวิเคราะห์ผ่าน handle


async def test_analyse_job_through_handle_makes_report(client, db, ai_config, analyser_ai, chats, replies):
    """D งาน kind analyse เข้า handle → ทำรายงาน · ไม่เรียกตัวคุย · ไม่ reply LINE"""
    from app.models.job import Job
    from app.workers import worker

    session_id, _ = await closed_session(db, ("user", "text", "ไฟถนนดับทั้งซอย"))
    analyser_ai.replies = [answer({"desc": "ไฟถนนดับทั้งซอย", "tags": ["ไฟถนน"], "location": None, "images": []})]

    await worker.handle(Job(kind="analyse", session_id=session_id))

    assert len(await reports_of(db, session_id)) == 1
    assert await status_of(db, session_id) == "analysed"
    assert chats == []
    assert replies == []
