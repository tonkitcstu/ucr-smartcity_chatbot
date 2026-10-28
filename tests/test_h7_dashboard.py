"""H7 ทีมออกแบบดึงรายงาน — S8 · spec ใน #155 · แบบ docs/designs/09-modules/h7-dashboard.puml

หน้าตา JSON: docs/designs/09-modules/h7-dashboard-api.md
ตำแหน่ง (lat / lng · แถว location) และสติกเกอร์ — H9 ท้ายไฟล์ · spec ใน #219
"""

import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

API_KEY = os.environ["DASHBOARD_API_KEY"]
LINE_USER_ID = "U_line_id_of_reporter"

REPORTS = "/api/dashboard/reports"
ATTACHMENTS = "/api/dashboard/attachments"
TRANSCRIPTS = "/api/dashboard/transcripts"


# header ที่ทีมแดชบอร์ดแนบมา · กุญแจดอกเดียวกับ DASHBOARD_API_KEY
def api_key(key=API_KEY):
    return {"Authorization": f"Bearer {key}"}


@pytest.fixture
async def ai_config(db):
    model = await db.fetchval("INSERT INTO models (provider, name) VALUES ('test', 'test-model') RETURNING model_id")
    prompt = await db.fetchval("INSERT INTO prompts (prompt) VALUES ('test prompt') RETURNING prompt_id")
    return await db.fetchval(
        """
        INSERT INTO ai_configs (chat_model_id, chat_prompt_id, analyzer_model_id, analyzer_prompt_id)
        VALUES ($1, $2, $1, $2) RETURNING ai_config_id
        """,
        model,
        prompt,
    )


async def conversation(db, tmp_path, *items, line_user_id=LINE_USER_ID):
    """ใบที่วิเคราะห์แล้ว · บทสนทนาตามลำดับ items · ไฟล์รูปเขียนลงดิสก์จริง

    item: ("user" | "assistant", "text", ข้อความ) · ("user", "image", เนื้อไฟล์)
          ("user", "location", (lat, lng)) · ("user", "sticker", keywords คั่นด้วยจุลภาค | None)
    """
    user_id = await db.fetchval(
        """
        INSERT INTO users (line_user_id, pdpa_accepted_at) VALUES ($1, now())
        ON CONFLICT (line_user_id) DO UPDATE SET line_user_id = EXCLUDED.line_user_id
        RETURNING user_id
        """,
        line_user_id,
    )
    session_id = await db.fetchval(
        """
        INSERT INTO sessions (user_id, status, started_at, last_message_at, closed_at)
        VALUES ($1, 'analysed', now() - interval '30 minutes', now() - interval '11 minutes', now())
        RETURNING session_id
        """,
        user_id,
    )
    message_ids, attachment_ids = [], []
    for order, (role, kind, value) in enumerate(items):
        message_id = await db.fetchval(
            """
            INSERT INTO messages (session_id, role, type, content, lat, lng, status, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, 'answered', now() - interval '30 minutes' + make_interval(secs => $7))
            RETURNING message_id
            """,
            session_id,
            role,
            kind,
            value if kind in ("text", "sticker") else None,
            *(value if kind == "location" else (None, None)),
            order,
        )
        message_ids.append(message_id)
        if kind == "image":
            path = tmp_path / f"{message_id}.jpg"
            path.write_bytes(value)
            attachment_ids.append(
                await db.fetchval(
                    "INSERT INTO attachments (message_id, type, file_path) VALUES ($1, 'image', $2) RETURNING attachment_id",
                    message_id,
                    str(path),
                )
            )
    return SimpleNamespace(
        user_id=user_id, session_id=session_id, message_ids=message_ids, attachment_ids=attachment_ids
    )


async def report(
    db, ai_config, talk, *, desc="น้ำท่วมหน้าบ้าน", tags=("น้ำท่วม",), created_at=None, attachment_ids=(), pin=(None, None)
):
    """รายงานหนึ่งใบของใบ talk · ผูกรูปตาม attachment_ids · pin = (lat, lng)"""
    report_id = await db.fetchval(
        """
        INSERT INTO reports (session_id, ai_config_id, tags, "desc", severity, started_at, created_at, lat, lng)
        SELECT $1, $2, $3, $4, 'medium', started_at, coalesce($5::timestamptz, now()), $6, $7
        FROM sessions WHERE session_id = $1
        RETURNING report_id
        """,
        talk.session_id,
        ai_config,
        list(tags),
        desc,
        created_at,
        *pin,
    )
    await db.execute(
        "UPDATE attachments SET report_id = $1 WHERE attachment_id = ANY($2::uuid[])", report_id, list(attachment_ids)
    )
    return report_id


async def simple_report(db, ai_config, tmp_path, **fields):
    talk = await conversation(db, tmp_path, ("user", "text", "น้ำท่วมหน้าบ้าน"))
    return await report(db, ai_config, talk, **fields)


def ids(response):
    return [item["report_id"] for item in response.json()]


# --- กุญแจ API (ทั้งสามเส้น) ---

ROUTES = [REPORTS, f"{ATTACHMENTS}/{uuid4()}", f"{TRANSCRIPTS}/{uuid4()}"]
ROUTE_IDS = ["reports", "attachments", "transcripts"]

REJECTED = {
    "no-header": lambda: {},
    "other-key": lambda: api_key("someone-elses-key"),
    "empty-key": lambda: api_key(""),
    "key-plus-more": lambda: api_key(API_KEY + "x"),
    "no-bearer-word": lambda: {"Authorization": API_KEY},
    "basic-instead": lambda: {"Authorization": f"Basic {API_KEY}"},
    "key-in-x-api-key": lambda: {"X-API-Key": API_KEY},
}


@pytest.mark.parametrize("path", ROUTES, ids=ROUTE_IDS)
@pytest.mark.parametrize("headers", list(REJECTED.values()), ids=list(REJECTED))
async def test_rejects_without_valid_api_key(client, path, headers):
    response = await client.get(path, headers=headers())

    assert response.status_code == 401


@pytest.mark.parametrize("path", ROUTES, ids=ROUTE_IDS)
async def test_locked_when_api_key_is_not_set(client, monkeypatch, path):
    from app.core import config

    monkeypatch.setattr(config, "DASHBOARD_API_KEY", None)

    response = await client.get(path, headers=api_key())

    assert response.status_code == 503


async def test_valid_api_key_passes(client):
    response = await client.get(REPORTS, headers=api_key())

    assert response.status_code == 200


# --- GET /reports ---


async def test_no_reports_gives_empty_list(client):
    response = await client.get(REPORTS, headers=api_key())

    assert response.json() == []


async def test_report_fields_match_database(client, db, ai_config, tmp_path):
    talk = await conversation(db, tmp_path, ("user", "text", "ฝนตกทีไรน้ำท่วมหน้าบ้าน"), ("user", "image", b"photo"))
    report_id = await report(
        db,
        ai_config,
        talk,
        desc="ฝนตกทีไรน้ำท่วมหน้าบ้าน สูงเกือบเข่า",
        tags=("น้ำท่วม", "ท่อระบายน้ำ"),
        attachment_ids=talk.attachment_ids,
    )
    row = await db.fetchrow("SELECT * FROM reports WHERE report_id = $1", report_id)

    response = await client.get(REPORTS, headers=api_key())

    [item] = response.json()
    assert item["report_id"] == str(report_id)
    assert item["session_id"] == str(talk.session_id)
    assert item["user_id"] == str(talk.user_id)
    assert item["desc"] == "ฝนตกทีไรน้ำท่วมหน้าบ้าน สูงเกือบเข่า"
    assert item["tags"] == ["น้ำท่วม", "ท่อระบายน้ำ"]
    assert item["attachments"] == [
        {"attachment_id": str(talk.attachment_ids[0]), "url": f"{ATTACHMENTS}/{talk.attachment_ids[0]}"}
    ]
    assert datetime.fromisoformat(item["started_at"]) == row["started_at"]
    assert datetime.fromisoformat(item["created_at"]) == row["created_at"]


# ช่องที่ตัววิเคราะห์ประเมิน: ความรุนแรง ใครได้รับผลกระทบ ช่วงเวลา ตำแหน่งตามคำ · ตรงกับในฐาน
async def test_report_has_severity_groups_times_and_place(client, db, ai_config, tmp_path):
    report_id = await simple_report(db, ai_config, tmp_path)
    await db.execute(
        """
        UPDATE reports SET severity = 'high', affected_groups = '{elderly,pedestrians}',
                           time_periods = '{morning,midday}', place = 'ทางเดินหน้าวัด'
        WHERE report_id = $1
        """,
        report_id,
    )

    response = await client.get(REPORTS, headers=api_key())

    [item] = response.json()
    assert item["severity"] == "high"
    assert item["affected_groups"] == ["elderly", "pedestrians"]
    assert item["time_periods"] == ["morning", "midday"]
    assert item["place"] == "ทางเดินหน้าวัด"


async def test_times_are_in_thai_time(client, db, ai_config, tmp_path):
    await simple_report(db, ai_config, tmp_path)

    response = await client.get(REPORTS, headers=api_key())

    [item] = response.json()
    assert datetime.fromisoformat(item["started_at"]).utcoffset() == timedelta(hours=7)
    assert datetime.fromisoformat(item["created_at"]).utcoffset() == timedelta(hours=7)


async def test_reporter_is_user_id_never_line_id(client, db, ai_config, tmp_path):
    await simple_report(db, ai_config, tmp_path)

    response = await client.get(REPORTS, headers=api_key())

    assert response.status_code == 200
    assert LINE_USER_ID not in response.text
    assert "line_user_id" not in response.text


@pytest.mark.parametrize("count", [0, 1, 3])
async def test_report_lists_all_its_attachments(client, db, ai_config, tmp_path, count):
    photos = [("user", "image", f"photo-{n}".encode()) for n in range(count)]
    talk = await conversation(db, tmp_path, ("user", "text", "น้ำท่วมหน้าบ้าน"), *photos)
    await report(db, ai_config, talk, attachment_ids=talk.attachment_ids)

    response = await client.get(REPORTS, headers=api_key())

    [item] = response.json()
    assert sorted(a["attachment_id"] for a in item["attachments"]) == sorted(map(str, talk.attachment_ids))
    assert all(a["url"] == f"{ATTACHMENTS}/{a['attachment_id']}" for a in item["attachments"])


async def test_photo_outside_the_report_is_not_listed(client, db, ai_config, tmp_path):
    talk = await conversation(db, tmp_path, ("user", "image", b"chosen"), ("user", "image", b"not-chosen"))
    await report(db, ai_config, talk, attachment_ids=talk.attachment_ids[:1])

    response = await client.get(REPORTS, headers=api_key())

    [item] = response.json()
    assert [a["attachment_id"] for a in item["attachments"]] == [str(talk.attachment_ids[0])]


async def test_reports_are_newest_first(client, db, ai_config, tmp_path):
    now = datetime.now(timezone.utc)
    old = await simple_report(db, ai_config, tmp_path, created_at=now - timedelta(days=2))
    new = await simple_report(db, ai_config, tmp_path, created_at=now)
    middle = await simple_report(db, ai_config, tmp_path, created_at=now - timedelta(days=1))

    response = await client.get(REPORTS, headers=api_key())

    assert ids(response) == [str(new), str(middle), str(old)]


async def test_date_filter_counts_the_day_in_thai_time(client, db, ai_config, tmp_path):
    """23:30 UTC ของวันที่ 9 = 06:30 ของวันที่ 10 ตามเวลาไทย"""
    late = await simple_report(db, ai_config, tmp_path, created_at=datetime(2026, 10, 9, 23, 30, tzinfo=timezone.utc))
    noon = await simple_report(db, ai_config, tmp_path, created_at=datetime(2026, 10, 9, 5, 0, tzinfo=timezone.utc))

    on_the_9th = await client.get(REPORTS, params={"date": "2026-10-09"}, headers=api_key())
    on_the_10th = await client.get(REPORTS, params={"date": "2026-10-10"}, headers=api_key())
    on_the_11th = await client.get(REPORTS, params={"date": "2026-10-11"}, headers=api_key())

    assert ids(on_the_9th) == [str(noon)]
    assert ids(on_the_10th) == [str(late)]
    assert ids(on_the_11th) == []


async def test_tag_filter_matches_a_whole_tag(client, db, ai_config, tmp_path):
    flood = await simple_report(db, ai_config, tmp_path, tags=("น้ำท่วม", "ขยะ"))
    await simple_report(db, ai_config, tmp_path, tags=("ความร้อน",))

    by_tag = await client.get(REPORTS, params={"tag": "ขยะ"}, headers=api_key())
    by_part_of_tag = await client.get(REPORTS, params={"tag": "น้ำ"}, headers=api_key())

    assert ids(by_tag) == [str(flood)]
    assert ids(by_part_of_tag) == []


async def test_date_and_tag_must_both_match(client, db, ai_config, tmp_path):
    day = datetime(2026, 10, 9, 5, 0, tzinfo=timezone.utc)
    wanted = await simple_report(db, ai_config, tmp_path, tags=("น้ำท่วม",), created_at=day)
    await simple_report(db, ai_config, tmp_path, tags=("ขยะ",), created_at=day)
    await simple_report(db, ai_config, tmp_path, tags=("น้ำท่วม",), created_at=day - timedelta(days=3))

    response = await client.get(REPORTS, params={"date": "2026-10-09", "tag": "น้ำท่วม"}, headers=api_key())

    assert ids(response) == [str(wanted)]


async def test_limit_defaults_to_20_and_keeps_the_newest(client, db, ai_config, tmp_path):
    now = datetime.now(timezone.utc)
    made = [await simple_report(db, ai_config, tmp_path, created_at=now - timedelta(minutes=n)) for n in range(25)]

    by_default = await client.get(REPORTS, headers=api_key())
    five = await client.get(REPORTS, params={"limit": 5}, headers=api_key())
    all_of_them = await client.get(REPORTS, params={"limit": 200}, headers=api_key())

    assert ids(by_default) == [str(r) for r in made[:20]]
    assert ids(five) == [str(r) for r in made[:5]]
    assert ids(all_of_them) == [str(r) for r in made]


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 201}, {"limit": "many"}, {"date": "10-10-2026"}, {"date": "yesterday"}],
    ids=["limit-0", "limit-201", "limit-word", "date-wrong-order", "date-word"],
)
async def test_wrong_query_is_rejected(client, params):
    response = await client.get(REPORTS, params=params, headers=api_key())

    assert response.status_code == 422


# --- GET /attachments/{attachment_id} ---


async def test_attachment_returns_the_stored_file(client, db, tmp_path):
    talk = await conversation(db, tmp_path, ("user", "image", b"\xff\xd8 the photo bytes"))

    response = await client.get(f"{ATTACHMENTS}/{talk.attachment_ids[0]}", headers=api_key())

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == b"\xff\xd8 the photo bytes"


async def test_url_in_report_opens_the_photo(client, db, ai_config, tmp_path):
    talk = await conversation(db, tmp_path, ("user", "image", b"photo of the flood"))
    await report(db, ai_config, talk, attachment_ids=talk.attachment_ids)

    [item] = (await client.get(REPORTS, headers=api_key())).json()
    response = await client.get(item["attachments"][0]["url"], headers=api_key())

    assert response.content == b"photo of the flood"


async def test_unknown_attachment_is_not_found(client):
    response = await client.get(f"{ATTACHMENTS}/{uuid4()}", headers=api_key())

    assert response.status_code == 404
    assert response.json() == {"detail": "Attachment not found"}


async def test_attachment_with_missing_file_is_not_found(client, db, tmp_path):
    talk = await conversation(db, tmp_path, ("user", "image", b"photo"))
    (tmp_path / f"{talk.message_ids[0]}.jpg").unlink()

    response = await client.get(f"{ATTACHMENTS}/{talk.attachment_ids[0]}", headers=api_key())

    assert response.status_code == 404
    assert response.json() == {"detail": "Attachment not found"}


async def test_attachment_id_must_be_uuid(client):
    response = await client.get(f"{ATTACHMENTS}/not-a-uuid", headers=api_key())

    assert response.status_code == 422


# --- GET /transcripts/{session_id} ---


async def test_transcript_has_every_message_in_order(client, db, tmp_path):
    talk = await conversation(
        db,
        tmp_path,
        ("user", "text", "น้ำท่วมหน้าบ้านอีกแล้ว"),
        ("user", "image", b"photo"),
        ("assistant", "text", "ท่วมสูงประมาณไหนคะ"),
        ("user", "text", "เกือบถึงเข่า"),
    )

    response = await client.get(f"{TRANSCRIPTS}/{talk.session_id}", headers=api_key())

    assert response.status_code == 200
    assert [(m["message_id"], m["role"], m["type"], m["content"]) for m in response.json()] == [
        (str(talk.message_ids[0]), "user", "text", "น้ำท่วมหน้าบ้านอีกแล้ว"),
        (str(talk.message_ids[1]), "user", "image", None),
        (str(talk.message_ids[2]), "assistant", "text", "ท่วมสูงประมาณไหนคะ"),
        (str(talk.message_ids[3]), "user", "text", "เกือบถึงเข่า"),
    ]


async def test_transcript_links_photos_without_file_path(client, db, tmp_path):
    talk = await conversation(db, tmp_path, ("user", "text", "น้ำท่วมหน้าบ้าน"), ("user", "image", b"photo"))

    response = await client.get(f"{TRANSCRIPTS}/{talk.session_id}", headers=api_key())

    text, photo = response.json()
    assert text["attachment"] is None
    assert photo["attachment"] == {
        "attachment_id": str(talk.attachment_ids[0]),
        "url": f"{ATTACHMENTS}/{talk.attachment_ids[0]}",
    }
    assert "file_path" not in response.text
    assert str(tmp_path) not in response.text


async def test_transcript_has_only_its_own_session(client, db, tmp_path):
    mine = await conversation(db, tmp_path, ("user", "text", "น้ำท่วมหน้าบ้าน"))
    await conversation(db, tmp_path, ("user", "text", "ขยะกองหน้าตลาด"), line_user_id="U_someone_else")

    response = await client.get(f"{TRANSCRIPTS}/{mine.session_id}", headers=api_key())

    assert [m["content"] for m in response.json()] == ["น้ำท่วมหน้าบ้าน"]


async def test_session_id_in_report_opens_its_transcript(client, db, ai_config, tmp_path):
    talk = await conversation(db, tmp_path, ("user", "text", "น้ำท่วมหน้าบ้าน"), ("assistant", "text", "ท่วมบ่อยไหมคะ"))
    await report(db, ai_config, talk)

    [item] = (await client.get(REPORTS, headers=api_key())).json()
    response = await client.get(f"{TRANSCRIPTS}/{item['session_id']}", headers=api_key())

    assert [m["content"] for m in response.json()] == ["น้ำท่วมหน้าบ้าน", "ท่วมบ่อยไหมคะ"]


async def test_unknown_session_is_not_found(client):
    response = await client.get(f"{TRANSCRIPTS}/{uuid4()}", headers=api_key())

    assert response.status_code == 404
    assert response.json() == {"detail": "Transcript not found"}


async def test_session_id_must_be_uuid(client):
    response = await client.get(f"{TRANSCRIPTS}/not-a-uuid", headers=api_key())

    assert response.status_code == 422


# --- H9 รับตำแหน่งและสติกเกอร์ — S4 S13 · spec ใน #219 · แบบ docs/designs/09-modules/h9-location-sticker.puml ---


async def test_transcript_has_pin_and_sticker_rows(client, db, tmp_path):
    """H9-14. ใบมีข้อความ + หมุด + สติกเกอร์ → เรียงตามเวลา · แถว location มี lat lng · แถว sticker มี content = keywords"""
    talk = await conversation(
        db,
        tmp_path,
        ("user", "text", "น้ำท่วมหน้าบ้านอีกแล้ว"),
        ("user", "location", (35.67966, 139.73669)),
        ("user", "sticker", "cony, sally, Staring, hi, wave, Hello"),
        ("user", "sticker", None),
        ("assistant", "text", "ท่วมสูงประมาณไหนคะ"),
    )

    response = await client.get(f"{TRANSCRIPTS}/{talk.session_id}", headers=api_key())

    assert response.status_code == 200
    assert [(m["role"], m["type"], m["content"], m["lat"], m["lng"]) for m in response.json()] == [
        ("user", "text", "น้ำท่วมหน้าบ้านอีกแล้ว", None, None),
        ("user", "location", None, 35.67966, 139.73669),
        ("user", "sticker", "cony, sally, Staring, hi, wave, Hello", None, None),
        ("user", "sticker", None, None, None),
        ("assistant", "text", "ท่วมสูงประมาณไหนคะ", None, None),
    ]
    assert all(m["attachment"] is None for m in response.json())


async def test_report_carries_its_pin(client, db, ai_config, tmp_path):
    """H9-15. รายงานที่มีพิกัด → lat lng ตรง · รายงานที่ไม่มี → null"""
    talk = await conversation(db, tmp_path, ("user", "text", "น้ำท่วมหน้าบ้าน"), ("user", "location", (35.67966, 139.73669)))
    pinned = await report(db, ai_config, talk, pin=(35.67966, 139.73669))
    plain = await report(db, ai_config, talk, desc="ขยะล้นถัง", tags=("ขยะ",))

    response = await client.get(REPORTS, headers=api_key())

    pins = {item["report_id"]: (item["lat"], item["lng"]) for item in response.json()}
    assert pins == {str(pinned): (35.67966, 139.73669), str(plain): (None, None)}


# --- #239 ② เพดานข้อความใน buffer ต่อใบ — spec ใน #239 · แบบ docs/designs/09-modules/239-buffer-limit.puml ---


async def test_transcript_keeps_skipped_messages(client, db, tmp_path):
    """239②-13. ใบมีข้อความ skipped → แดชบอร์ดเห็นทุกข้อความรวมข้อความ skipped ตามลำดับเวลา (S23)"""
    talk = await conversation(
        db,
        tmp_path,
        ("user", "text", "สแปม"),
        ("user", "image", b"spam"),
        ("user", "text", "น้ำท่วมหน้าบ้าน"),
        ("assistant", "text", "ท่วมสูงประมาณไหนคะ"),
    )
    await db.execute("UPDATE messages SET status = 'skipped' WHERE message_id = ANY($1::uuid[])", talk.message_ids[:2])

    response = await client.get(f"{TRANSCRIPTS}/{talk.session_id}", headers=api_key())

    assert response.status_code == 200
    assert [m["message_id"] for m in response.json()] == [str(message_id) for message_id in talk.message_ids]


async def test_transcript_tells_which_messages_were_skipped(client, db, tmp_path):
    """แดชบอร์ดแยกได้ว่าข้อความไหนบอทไม่ได้ตอบ · ช่อง status ตรงกับ PSQL"""
    talk = await conversation(
        db,
        tmp_path,
        ("user", "text", "สแปม"),
        ("user", "text", "น้ำท่วมหน้าบ้าน"),
        ("assistant", "text", "ท่วมสูงประมาณไหนคะ"),
    )
    await db.execute("UPDATE messages SET status = 'skipped' WHERE message_id = $1", talk.message_ids[0])

    response = await client.get(f"{TRANSCRIPTS}/{talk.session_id}", headers=api_key())

    assert [m["status"] for m in response.json()] == ["skipped", "answered", "answered"]


# --- ตัวกรองความรุนแรงกับช่วงวัน + รายงานใบเดียว — S33 · spec docs/designs/09-modules/h7-dashboard-api.md ---


# รายงานที่ helper report() สร้างเป็น medium เสมอ · ตั้งความรุนแรงที่ต้องการทีหลัง
async def set_severity(db, report_id, severity):
    await db.execute("UPDATE reports SET severity = $2 WHERE report_id = $1", report_id, severity)


# เวลาไทยของวันที่ day เวลา hour นาฬิกา เก็บเป็น UTC แบบที่ฐานเก็บ
def thai(day, hour=12):
    return datetime(2026, 10, day, hour, 0, tzinfo=timezone(timedelta(hours=7))).astimezone(timezone.utc)


# ได้เฉพาะรายงานที่ความรุนแรงตรง
async def test_severity_filter_keeps_only_that_level(client, db, ai_config, tmp_path):
    made = {}
    for level in ("low", "medium", "high"):
        made[level] = await simple_report(db, ai_config, tmp_path)
        await set_severity(db, made[level], level)

    response = await client.get(REPORTS, params={"severity": "high"}, headers=api_key())

    assert ids(response) == [str(made["high"])]


# ความรุนแรงมีแค่ low medium high ตัวพิมพ์เล็ก
@pytest.mark.parametrize("severity", ["severe", "HIGH"])
async def test_unknown_severity_is_rejected(client, severity):
    response = await client.get(REPORTS, params={"severity": severity}, headers=api_key())

    assert response.status_code == 422


# ช่วงวันนับวันแรกและวันสุดท้ายด้วย · ตัดวันตามเวลาไทย
async def test_date_range_includes_both_end_days_in_thai_time(client, db, ai_config, tmp_path):
    before = await simple_report(db, ai_config, tmp_path, created_at=thai(8, 23))
    first_day = await simple_report(db, ai_config, tmp_path, created_at=thai(9, 0))
    middle = await simple_report(db, ai_config, tmp_path, created_at=thai(10))
    last_day = await simple_report(db, ai_config, tmp_path, created_at=thai(11, 23))
    after = await simple_report(db, ai_config, tmp_path, created_at=thai(12, 0))

    response = await client.get(
        REPORTS, params={"start_date": "2026-10-09", "end_date": "2026-10-11"}, headers=api_key()
    )

    assert ids(response) == [str(last_day), str(middle), str(first_day)]
    assert str(before) not in ids(response) and str(after) not in ids(response)


# ใส่แค่ start_date → ตั้งแต่วันนั้นเป็นต้นไป
async def test_start_date_alone_keeps_that_day_onwards(client, db, ai_config, tmp_path):
    await simple_report(db, ai_config, tmp_path, created_at=thai(9))
    on_the_day = await simple_report(db, ai_config, tmp_path, created_at=thai(10))
    later = await simple_report(db, ai_config, tmp_path, created_at=thai(20))

    response = await client.get(REPORTS, params={"start_date": "2026-10-10"}, headers=api_key())

    assert ids(response) == [str(later), str(on_the_day)]


# ใส่แค่ end_date → ทุกใบจนถึงวันนั้น
async def test_end_date_alone_keeps_up_to_that_day(client, db, ai_config, tmp_path):
    earlier = await simple_report(db, ai_config, tmp_path, created_at=thai(1))
    on_the_day = await simple_report(db, ai_config, tmp_path, created_at=thai(10))
    await simple_report(db, ai_config, tmp_path, created_at=thai(11))

    response = await client.get(REPORTS, params={"end_date": "2026-10-10"}, headers=api_key())

    assert ids(response) == [str(on_the_day), str(earlier)]


# วันเริ่มเลยวันจบ → ไม่มีวันไหนอยู่ในช่วง ได้รายการว่าง ไม่ใช่ error
async def test_start_after_end_gives_empty_list(client, db, ai_config, tmp_path):
    await simple_report(db, ai_config, tmp_path, created_at=thai(10))

    response = await client.get(
        REPORTS, params={"start_date": "2026-10-11", "end_date": "2026-10-09"}, headers=api_key()
    )

    assert response.status_code == 200
    assert response.json() == []


# ใส่ป้าย ความรุนแรง และช่วงวันพร้อมกัน → ต้องตรงทุกตัว · ใบหลอกแต่ละใบผิดไปตัวเดียว
async def test_tag_severity_and_range_must_all_match(client, db, ai_config, tmp_path):
    wanted = await simple_report(db, ai_config, tmp_path, tags=("น้ำท่วม",), created_at=thai(10))
    wrong_tag = await simple_report(db, ai_config, tmp_path, tags=("ขยะ",), created_at=thai(10))
    wrong_severity = await simple_report(db, ai_config, tmp_path, tags=("น้ำท่วม",), created_at=thai(10))
    out_of_range = await simple_report(db, ai_config, tmp_path, tags=("น้ำท่วม",), created_at=thai(20))
    for report_id in (wanted, wrong_tag, out_of_range):
        await set_severity(db, report_id, "high")

    response = await client.get(
        REPORTS,
        params={"tag": "น้ำท่วม", "severity": "high", "start_date": "2026-10-09", "end_date": "2026-10-11"},
        headers=api_key(),
    )

    assert ids(response) == [str(wanted)]
    assert str(wrong_severity) not in ids(response)


@pytest.mark.parametrize(
    "params",
    [{"start_date": "10-10-2026"}, {"end_date": "yesterday"}],
    ids=["start-wrong-order", "end-word"],
)
async def test_wrong_range_date_is_rejected(client, params):
    response = await client.get(REPORTS, params=params, headers=api_key())

    assert response.status_code == 422


# --- GET /reports/{report_id} ---


# รายงานใบเดียวหน้าตาเหมือนหนึ่งใบในรายการทุกช่อง
async def test_one_report_matches_its_item_in_the_list(client, db, ai_config, tmp_path):
    talk = await conversation(db, tmp_path, ("user", "text", "น้ำท่วมหน้าบ้าน"), ("user", "image", b"photo"))
    report_id = await report(db, ai_config, talk, attachment_ids=talk.attachment_ids, pin=(13.75, 100.5))
    await simple_report(db, ai_config, tmp_path, desc="ขยะล้นถัง", tags=("ขยะ",))

    [item] = [item for item in (await client.get(REPORTS, headers=api_key())).json() if item["report_id"] == str(report_id)]
    response = await client.get(f"{REPORTS}/{report_id}", headers=api_key())

    assert response.status_code == 200
    assert response.json() == item


async def test_unknown_report_is_not_found(client):
    response = await client.get(f"{REPORTS}/{uuid4()}", headers=api_key())

    assert response.status_code == 404
    assert response.json() == {"detail": "Report not found"}


async def test_report_id_must_be_uuid(client):
    response = await client.get(f"{REPORTS}/not-a-uuid", headers=api_key())

    assert response.status_code == 422


# เส้นใหม่ต้องผ่านด่านกุญแจ API เหมือนสามเส้นเดิม
@pytest.mark.parametrize("headers", list(REJECTED.values()), ids=list(REJECTED))
async def test_one_report_rejects_without_valid_api_key(client, headers):
    response = await client.get(f"{REPORTS}/{uuid4()}", headers=headers())

    assert response.status_code == 401


async def test_one_report_locked_when_api_key_is_not_set(client, monkeypatch):
    from app.core import config

    monkeypatch.setattr(config, "DASHBOARD_API_KEY", None)

    response = await client.get(f"{REPORTS}/{uuid4()}", headers=api_key())

    assert response.status_code == 503
