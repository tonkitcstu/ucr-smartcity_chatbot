"""H7 ทีมออกแบบดึงรายงาน — S8 · spec ใน #155 · แบบ docs/designs/09-modules/h7-dashboard.puml

หน้าตา JSON: docs/designs/09-modules/h7-dashboard-api.md
ยังไม่เทสตำแหน่ง (lat / lng · แถว location) — controller ยังไม่รับตำแหน่งจาก LINE
"""

import base64
import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

SECRET = os.environ["SECRET_KEY"]
LINE_USER_ID = "U_line_id_of_reporter"

REPORTS = "/api/dashboard/reports"
ATTACHMENTS = "/api/dashboard/attachments"
TRANSCRIPTS = "/api/dashboard/transcripts"


def token(key=SECRET, **claims):
    """JWT แบบที่ทีมออกแบบออกให้ — HS256 เซ็นด้วยกุญแจที่ถือร่วมกัน"""

    def part(data):
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=")

    claims = {"sub": "dashboard", "role": "admin", "exp": int(time.time()) + 3600} | claims
    claims = {name: value for name, value in claims.items() if value is not None}
    body = part({"alg": "HS256", "typ": "JWT"}) + b"." + part(claims)
    signature = base64.urlsafe_b64encode(hmac.new(key.encode(), body, hashlib.sha256).digest()).rstrip(b"=")
    return (body + b"." + signature).decode()


def bearer(**claims):
    return {"Authorization": f"Bearer {token(**claims)}"}


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
            INSERT INTO messages (session_id, role, type, content, status, created_at)
            VALUES ($1, $2, $3, $4, 'answered', now() - interval '30 minutes' + make_interval(secs => $5))
            RETURNING message_id
            """,
            session_id,
            role,
            kind,
            value if kind == "text" else None,
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


async def report(db, ai_config, talk, *, desc="น้ำท่วมหน้าบ้าน", tags=("น้ำท่วม",), created_at=None, attachment_ids=()):
    """รายงานหนึ่งใบของใบ talk · ผูกรูปตาม attachment_ids"""
    report_id = await db.fetchval(
        """
        INSERT INTO reports (session_id, ai_config_id, tags, "desc", started_at, created_at)
        SELECT $1, $2, $3, $4, started_at, coalesce($5::timestamptz, now()) FROM sessions WHERE session_id = $1
        RETURNING report_id
        """,
        talk.session_id,
        ai_config,
        list(tags),
        desc,
        created_at,
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


# --- JWT (ทั้งสามเส้น) ---

ROUTES = [REPORTS, f"{ATTACHMENTS}/{uuid4()}", f"{TRANSCRIPTS}/{uuid4()}"]
ROUTE_IDS = ["reports", "attachments", "transcripts"]

REJECTED = {
    "no-header": lambda: {},
    "not-bearer": lambda: {"Authorization": "Basic dWNyOnBhc3N3b3Jk"},
    "other-key": lambda: {"Authorization": f"Bearer {token(key='someone-elses-key-0000000000000000')}"},
    "expired": lambda: bearer(exp=int(time.time()) - 60),
    "no-sub": lambda: bearer(sub=None),
    "not-a-token": lambda: {"Authorization": "Bearer not-a-token"},
}


@pytest.mark.parametrize("path", ROUTES, ids=ROUTE_IDS)
@pytest.mark.parametrize("headers", list(REJECTED.values()), ids=list(REJECTED))
async def test_rejects_without_valid_jwt(client, path, headers):
    response = await client.get(path, headers=headers())

    assert response.status_code == 401


@pytest.mark.parametrize("path", ROUTES, ids=ROUTE_IDS)
async def test_locked_when_secret_key_is_not_set(client, monkeypatch, path):
    from app.core import config
    from app.services import auth

    monkeypatch.setattr(config, "SECRET_KEY", None)
    monkeypatch.setattr(auth, "SECRET_KEY", None)

    response = await client.get(path, headers=bearer())

    assert response.status_code == 503


async def test_valid_jwt_passes(client):
    response = await client.get(REPORTS, headers=bearer())

    assert response.status_code == 200


# --- GET /reports ---


async def test_no_reports_gives_empty_list(client):
    response = await client.get(REPORTS, headers=bearer())

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

    response = await client.get(REPORTS, headers=bearer())

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


async def test_times_are_in_thai_time(client, db, ai_config, tmp_path):
    await simple_report(db, ai_config, tmp_path)

    response = await client.get(REPORTS, headers=bearer())

    [item] = response.json()
    assert datetime.fromisoformat(item["started_at"]).utcoffset() == timedelta(hours=7)
    assert datetime.fromisoformat(item["created_at"]).utcoffset() == timedelta(hours=7)


async def test_reporter_is_user_id_never_line_id(client, db, ai_config, tmp_path):
    await simple_report(db, ai_config, tmp_path)

    response = await client.get(REPORTS, headers=bearer())

    assert response.status_code == 200
    assert LINE_USER_ID not in response.text
    assert "line_user_id" not in response.text


@pytest.mark.parametrize("count", [0, 1, 3])
async def test_report_lists_all_its_attachments(client, db, ai_config, tmp_path, count):
    photos = [("user", "image", f"photo-{n}".encode()) for n in range(count)]
    talk = await conversation(db, tmp_path, ("user", "text", "น้ำท่วมหน้าบ้าน"), *photos)
    await report(db, ai_config, talk, attachment_ids=talk.attachment_ids)

    response = await client.get(REPORTS, headers=bearer())

    [item] = response.json()
    assert sorted(a["attachment_id"] for a in item["attachments"]) == sorted(map(str, talk.attachment_ids))
    assert all(a["url"] == f"{ATTACHMENTS}/{a['attachment_id']}" for a in item["attachments"])


async def test_photo_outside_the_report_is_not_listed(client, db, ai_config, tmp_path):
    talk = await conversation(db, tmp_path, ("user", "image", b"chosen"), ("user", "image", b"not-chosen"))
    await report(db, ai_config, talk, attachment_ids=talk.attachment_ids[:1])

    response = await client.get(REPORTS, headers=bearer())

    [item] = response.json()
    assert [a["attachment_id"] for a in item["attachments"]] == [str(talk.attachment_ids[0])]


async def test_reports_are_newest_first(client, db, ai_config, tmp_path):
    now = datetime.now(timezone.utc)
    old = await simple_report(db, ai_config, tmp_path, created_at=now - timedelta(days=2))
    new = await simple_report(db, ai_config, tmp_path, created_at=now)
    middle = await simple_report(db, ai_config, tmp_path, created_at=now - timedelta(days=1))

    response = await client.get(REPORTS, headers=bearer())

    assert ids(response) == [str(new), str(middle), str(old)]


async def test_date_filter_counts_the_day_in_thai_time(client, db, ai_config, tmp_path):
    """23:30 UTC ของวันที่ 9 = 06:30 ของวันที่ 10 ตามเวลาไทย"""
    late = await simple_report(db, ai_config, tmp_path, created_at=datetime(2026, 10, 9, 23, 30, tzinfo=timezone.utc))
    noon = await simple_report(db, ai_config, tmp_path, created_at=datetime(2026, 10, 9, 5, 0, tzinfo=timezone.utc))

    on_the_9th = await client.get(REPORTS, params={"date": "2026-10-09"}, headers=bearer())
    on_the_10th = await client.get(REPORTS, params={"date": "2026-10-10"}, headers=bearer())
    on_the_11th = await client.get(REPORTS, params={"date": "2026-10-11"}, headers=bearer())

    assert ids(on_the_9th) == [str(noon)]
    assert ids(on_the_10th) == [str(late)]
    assert ids(on_the_11th) == []


async def test_tag_filter_matches_a_whole_tag(client, db, ai_config, tmp_path):
    flood = await simple_report(db, ai_config, tmp_path, tags=("น้ำท่วม", "ขยะ"))
    await simple_report(db, ai_config, tmp_path, tags=("ความร้อน",))

    by_tag = await client.get(REPORTS, params={"tag": "ขยะ"}, headers=bearer())
    by_part_of_tag = await client.get(REPORTS, params={"tag": "น้ำ"}, headers=bearer())

    assert ids(by_tag) == [str(flood)]
    assert ids(by_part_of_tag) == []


async def test_date_and_tag_must_both_match(client, db, ai_config, tmp_path):
    day = datetime(2026, 10, 9, 5, 0, tzinfo=timezone.utc)
    wanted = await simple_report(db, ai_config, tmp_path, tags=("น้ำท่วม",), created_at=day)
    await simple_report(db, ai_config, tmp_path, tags=("ขยะ",), created_at=day)
    await simple_report(db, ai_config, tmp_path, tags=("น้ำท่วม",), created_at=day - timedelta(days=3))

    response = await client.get(REPORTS, params={"date": "2026-10-09", "tag": "น้ำท่วม"}, headers=bearer())

    assert ids(response) == [str(wanted)]


async def test_limit_defaults_to_20_and_keeps_the_newest(client, db, ai_config, tmp_path):
    now = datetime.now(timezone.utc)
    made = [await simple_report(db, ai_config, tmp_path, created_at=now - timedelta(minutes=n)) for n in range(25)]

    by_default = await client.get(REPORTS, headers=bearer())
    five = await client.get(REPORTS, params={"limit": 5}, headers=bearer())
    all_of_them = await client.get(REPORTS, params={"limit": 200}, headers=bearer())

    assert ids(by_default) == [str(r) for r in made[:20]]
    assert ids(five) == [str(r) for r in made[:5]]
    assert ids(all_of_them) == [str(r) for r in made]


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 201}, {"limit": "many"}, {"date": "10-10-2026"}, {"date": "yesterday"}],
    ids=["limit-0", "limit-201", "limit-word", "date-wrong-order", "date-word"],
)
async def test_wrong_query_is_rejected(client, params):
    response = await client.get(REPORTS, params=params, headers=bearer())

    assert response.status_code == 422


# --- GET /attachments/{attachment_id} ---


async def test_attachment_returns_the_stored_file(client, db, tmp_path):
    talk = await conversation(db, tmp_path, ("user", "image", b"\xff\xd8 the photo bytes"))

    response = await client.get(f"{ATTACHMENTS}/{talk.attachment_ids[0]}", headers=bearer())

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == b"\xff\xd8 the photo bytes"


async def test_url_in_report_opens_the_photo(client, db, ai_config, tmp_path):
    talk = await conversation(db, tmp_path, ("user", "image", b"photo of the flood"))
    await report(db, ai_config, talk, attachment_ids=talk.attachment_ids)

    [item] = (await client.get(REPORTS, headers=bearer())).json()
    response = await client.get(item["attachments"][0]["url"], headers=bearer())

    assert response.content == b"photo of the flood"


async def test_unknown_attachment_is_not_found(client):
    response = await client.get(f"{ATTACHMENTS}/{uuid4()}", headers=bearer())

    assert response.status_code == 404
    assert response.json() == {"detail": "Attachment not found"}


async def test_attachment_with_missing_file_is_not_found(client, db, tmp_path):
    talk = await conversation(db, tmp_path, ("user", "image", b"photo"))
    (tmp_path / f"{talk.message_ids[0]}.jpg").unlink()

    response = await client.get(f"{ATTACHMENTS}/{talk.attachment_ids[0]}", headers=bearer())

    assert response.status_code == 404
    assert response.json() == {"detail": "Attachment not found"}


async def test_attachment_id_must_be_uuid(client):
    response = await client.get(f"{ATTACHMENTS}/not-a-uuid", headers=bearer())

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

    response = await client.get(f"{TRANSCRIPTS}/{talk.session_id}", headers=bearer())

    assert response.status_code == 200
    assert [(m["message_id"], m["role"], m["type"], m["content"]) for m in response.json()] == [
        (str(talk.message_ids[0]), "user", "text", "น้ำท่วมหน้าบ้านอีกแล้ว"),
        (str(talk.message_ids[1]), "user", "image", None),
        (str(talk.message_ids[2]), "assistant", "text", "ท่วมสูงประมาณไหนคะ"),
        (str(talk.message_ids[3]), "user", "text", "เกือบถึงเข่า"),
    ]


async def test_transcript_links_photos_without_file_path(client, db, tmp_path):
    talk = await conversation(db, tmp_path, ("user", "text", "น้ำท่วมหน้าบ้าน"), ("user", "image", b"photo"))

    response = await client.get(f"{TRANSCRIPTS}/{talk.session_id}", headers=bearer())

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

    response = await client.get(f"{TRANSCRIPTS}/{mine.session_id}", headers=bearer())

    assert [m["content"] for m in response.json()] == ["น้ำท่วมหน้าบ้าน"]


async def test_session_id_in_report_opens_its_transcript(client, db, ai_config, tmp_path):
    talk = await conversation(db, tmp_path, ("user", "text", "น้ำท่วมหน้าบ้าน"), ("assistant", "text", "ท่วมบ่อยไหมคะ"))
    await report(db, ai_config, talk)

    [item] = (await client.get(REPORTS, headers=bearer())).json()
    response = await client.get(f"{TRANSCRIPTS}/{item['session_id']}", headers=bearer())

    assert [m["content"] for m in response.json()] == ["น้ำท่วมหน้าบ้าน", "ท่วมบ่อยไหมคะ"]


async def test_unknown_session_is_not_found(client):
    response = await client.get(f"{TRANSCRIPTS}/{uuid4()}", headers=bearer())

    assert response.status_code == 404
    assert response.json() == {"detail": "Transcript not found"}


async def test_session_id_must_be_uuid(client):
    response = await client.get(f"{TRANSCRIPTS}/not-a-uuid", headers=bearer())

    assert response.status_code == 422
