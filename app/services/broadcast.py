"""ตอนเราเป็นฝ่ายทักก่อน — ทักหาใคร ทักเรื่องอะไร แล้วจดว่าทักไปแล้ว

ปกติชาวบ้านทักมาหาเราแล้ว survey.py ค่อยคุยต่อ ไฟล์นี้กลับด้าน: เราพิมพ์ทักไปก่อน
เขาตอบมาเป็นภาษาคน แล้วบทสนทนาก็ไหลเข้า survey.py ตัวเดิม ต่างกันแค่
`source='broadcast'` — **ไม่มีเส้นทางเก็บข้อมูลเส้นที่สอง** ใบที่ได้ลงตาราง
reports ใบเดียวกัน มีต้นฉบับบทสนทนาเก็บที่เดียวกัน

**ข้อความเปิดเป็นของที่ AI แต่ง ไม่ใช่ข้อความสำเร็จรูป และไม่มีปุ่มให้กด**
ที่นี่บอกมันแค่ว่าอากาศแถวนั้นเป็นยังไง ที่เหลือมันเขียนเอง เพราะทั้งโปรเจกต์นี้
เดินมาจากการทิ้งคำถามตายตัว — การ์ดปุ่ม "ท่วม/ไม่ท่วม" ได้คำตอบเป็นเช็คบ็อกซ์
ซึ่ง sensor ก็ตอบได้อยู่แล้ว **ของที่เราต้องการคือเรื่องที่เขาเล่า**

ไฟล์นี้ไม่รู้จักช่องทางแชท เหมือน survey.py — คนเรียกส่งฟังก์ชันยิงเข้ามาให้
(พารามิเตอร์ `send`) วันหลังเพิ่มช่องทางใหม่จะได้เพิ่มแค่ไฟล์ใน api/

เฟสแรก **คนเป็นคนกดทัก** เลือกเรื่องเอง ยังไม่มีพยากรณ์อากาศเป็นคนเลือก
และยังไม่มีตัวตั้งเวลา ตรงนั้นเป็นเฟสถัดไป (ดู local/broadcast-v2/PORT.md)
"""

import logging
from datetime import datetime, timedelta, timezone

import asyncpg
from redis.asyncio import Redis

from app.clients import audience, llm
from app.services import draft, lock

log = logging.getLogger(__name__)

# ---------------------------------------------------------------- นโยบาย

# **หนึ่งคน ทักได้สัปดาห์ละครั้ง**
PERSON_CAP_DAYS = 7

# **หนึ่งชุมชน ก็สัปดาห์ละครั้ง** ของเดิมมี cap แค่ชั้นบน ผลคือวันนี้ทักกลุ่ม A
# พรุ่งนี้ทักกลุ่ม B คนแถวเดียวกันโดนทักทุกวันได้ แค่บังเอิญเป็นคนละคน
# ชั้นนี้กันเรื่องนั้น — สองชั้นนี้อยู่คนละระดับกัน ไม่ใช่ของซ้ำ
COMMUNITY_CAP_DAYS = 7

# ยังไม่มีหน้าต่างเวลา (08:00–20:00) เพราะเฟสนี้คนกดเป็นคนคุมเวลาอยู่แล้ว
# **วันที่ต่อตัวตั้งเวลาอัตโนมัติ อันนี้ต้องมาก่อนเปิดสวิตช์** ของเดิมเลือก
# ช่วงที่อากาศแรงที่สุดของวัน ฝนแรงสุดตีสามก็ทักตีสาม ไม่มีอะไรกั้น


# ------------------------------------------------------- เรื่องที่ทักไปคุยได้

# มีแค่ "สถานการณ์" ไม่มีคำถาม ไม่มีคำทักทาย **ของพวกนั้นเป็นงานของ AI**
# ที่นี่เก็บแค่สิ่งที่เรารู้จริงจากพยากรณ์อากาศ แล้วส่งให้มันไปเขียน
TOPICS = {
    "flood": {
        "label": "ฝนตก / น้ำท่วมขัง",
        "situation": "ช่วงนี้ฝนตกแถวบ้านเขา",
    },
    "heat": {
        "label": "อากาศร้อน",
        "situation": "ช่วงนี้อากาศแถวบ้านเขาร้อนจัด",
    },
    "both": {
        "label": "ฝนตกแต่ยังร้อนอบอ้าว",
        "situation": "ช่วงนี้แถวบ้านเขาฝนตกแต่อากาศยังร้อนอบอ้าว",
    },
}


OPENING_PROMPT = """คุณคือ "น้องเมือง" **ผู้หญิง** เก็บเสียงคนในชุมชนเรื่องสภาพแวดล้อมเมือง
ให้ทีมออกแบบเอาไปตัดสินใจว่าควรปรับปรุงตรงไหนก่อน

เขียนข้อความ **ทักไปหาเขาก่อน** ทางแชท เขาไม่ได้ทักมาหาเรา
สิ่งที่เรารู้มาจากพยากรณ์อากาศเท่านั้นคือ: {situation}

กติกา
- สั้น ไม่เกินสองประโยค ยาวกว่านี้คนไม่อ่าน
- ลงท้ายด้วยคำถาม **ปลายเปิดที่ต้องเล่าถึงจะตอบได้** ห้ามเป็นคำถามที่ตอบว่า
  ใช่/ไม่ใช่ แล้วจบ เพราะคำตอบแบบนั้น sensor ก็บอกได้อยู่แล้ว
  สิ่งที่เราอยากได้คือเรื่องที่เขาเจอ
- **เรารู้แค่พยากรณ์อากาศ ไม่รู้ว่าบ้านเขาเป็นยังไง** ห้ามเขียนเหมือนรู้อยู่แล้ว
  ว่าเขาเดือดร้อน ห้ามสมมติว่าน้ำท่วมบ้านเขาหรือเขาทนร้อนไม่ไหว
- **เราไม่ใช่ศูนย์ช่วยเหลือ ห้ามสัญญาว่าจะไปแก้ให้**
- ขอโทษที่รบกวนสั้น ๆ ได้ แต่อย่าอ้อมค้อม
- สุภาพแบบคนคุยกัน ลงท้าย "ค่ะ/คะ" ใช้อีโมจิได้ไม่เกินหนึ่งตัว
- **ตอบกลับมาเป็นตัวข้อความล้วน ๆ** ห้ามมีคำอธิบาย ห้ามใส่เครื่องหมายคำพูดคร่อม
{where}"""


class NoMessage(Exception):
    """แต่งข้อความเปิดไม่สำเร็จ — ไม่ส่งอะไรออกไปดีกว่าส่งของสำเร็จรูป"""


async def opening(topic: str, where: str | None = None) -> str:
    """ให้ AI แต่งข้อความเปิดบทสนทนา คืนตัวข้อความ

    ล้มแล้ว **ไม่มีข้อความสำรอง** ตั้งใจ — ข้อความสำรองก็คือคำถามตายตัวที่เรา
    ตั้งใจเลิกใช้ ถ้าโมเดลล่มก็ไม่ต้องทักวันนี้ พรุ่งนี้ค่อยทักไม่มีใครเดือดร้อน
    """
    if topic not in TOPICS:
        raise ValueError(f"ไม่รู้จักเรื่อง {topic!r}")

    prompt = OPENING_PROMPT.format(
        situation=TOPICS[topic]["situation"],
        where=f"\n- เขาอยู่{where} เอ่ยถึงได้ถ้ามันทำให้ข้อความเป็นธรรมชาติขึ้น" if where else "",
    )

    try:
        text, _used = await llm.chat([{"role": "user", "content": prompt}])
        text = text.strip()
    except Exception as exc:
        raise NoMessage("โมเดลแต่งข้อความเปิดไม่สำเร็จ") from exc

    # โมเดลชอบใส่อัญประกาศคร่อมทั้งข้อความเวลาถูกสั่งให้ "เขียนข้อความ"
    text = text.strip().strip('"').strip("“”").strip()
    if not text:
        raise NoMessage("โมเดลคืนข้อความว่าง")

    return text


# ------------------------------------------------------------ ตัวเชื่อม


async def send_one(
    pool: asyncpg.Pool,
    r: Redis,
    session_id: str,
    topic: str,
    send,
    text: str | None = None,
    force: bool = False,
) -> dict:
    """ทักคนเดียว — คนกดเลือกเองว่าจะทักใคร

    `text` ใส่มาแล้วใช้ตามนั้น (คนกดอ่านแล้วแก้เองก่อนส่ง) ไม่ใส่ก็ให้ AI แต่งสด
    """
    summary = {
        "status": "ok", "topic": topic, "text": text,
        "recipients": [], "sent": [], "failed": [],
        "skipped_cap": [], "skipped_talking": [], "skipped_recent": [],
    }

    if held := await _hold(r, session_id):
        summary["status"] = "skipped"
        summary[held] = [session_id]
        # เหลืออีกกี่นาทีถึงจะทักได้ — คนกดต้องรู้ ไม่ใช่โดนปฏิเสธลอย ๆ
        summary["wait_seconds"] = await seconds_left(r, session_id)
        return summary

    if not force and await _capped(pool, session_id):
        summary["status"] = "skipped"
        summary["skipped_cap"] = [session_id]
        return summary

    where = await audience.community_of(pool, session_id)
    community_id = await audience.community_id(pool, where) if where else None

    summary["recipients"] = [session_id]
    return summary | await _deliver(
        pool, r, [session_id], topic, text, send, community_id, where
    )


async def run(
    pool: asyncpg.Pool,
    r: Redis,
    community: str,
    topic: str,
    send,
    text: str | None = None,
    force: bool = False,
) -> dict:
    """ทักทั้งชุมชนหนึ่งรอบ คืนสรุปว่าถึงใคร ข้ามใคร เพราะอะไร

    `send(recipients, text) -> {"sent": [...], "failed": [...]}` คนเรียกส่งเข้ามา
    ไฟล์นี้จะได้ไม่ต้องรู้จักช่องทางแชท

    `force=True` ข้าม cap ทั้งสองชั้น — คันโยกไว้เดโม่ **แต่ไม่เคยข้ามข้อห้าม
    ที่ว่าห้ามทักทับคนที่กำลังคุยค้างอยู่** อันนั้นไม่ใช่นโยบายกันสแปม
    อันนั้นคือการขัดจังหวะคนที่กำลังเล่าเรื่องให้เราฟังอยู่

    สรุปที่คืนมาต้องอธิบายตัวเองได้ทั้งหมด — "ถึง 0 คน" ต้องบอกได้ว่าเพราะ
    ไม่มีใครในชุมชนนี้ หรือทุกคนติด cap หรือทุกคนกำลังคุยอยู่ คนละเรื่องกันสิ้นเชิง
    """
    if topic not in TOPICS:
        raise ValueError(f"ไม่รู้จักเรื่อง {topic!r}")

    summary = {
        "status": "ok", "community": community, "topic": topic, "text": text,
        "members": 0, "recipients": [], "sent": [], "failed": [],
        "skipped_cap": [], "skipped_talking": [], "skipped_recent": [],
        "skipped_error": [],
    }

    community_id = await audience.community_id(pool, community)
    if community_id is None:
        # สะกดชื่อไม่ตรงตาราง — เงียบไม่ได้ ไม่งั้นจะเข้าใจว่าทักแล้วแต่ไม่มีใครอยู่
        summary["status"] = "unknown-community"
        return summary

    # กันสองรอบทับกัน: ขึ้นหลาย worker ทุกตัวอ่าน outreach พร้อมกันก่อนที่ใคร
    # จะทันเขียนแถวลง แล้วต่างคนต่างทัก cap ช่วยไม่ได้เพราะมันแข่งกันอ่าน
    # `wait=0` — รอบที่มาทีหลังไม่ต้องต่อคิว ยอมแพ้ไปเลย รอบแรกทำให้แล้ว
    try:
        async with lock.one_at_a_time(r, f"broadcast:{community}", wait=0):
            return await _round(
                pool, r, community, community_id, topic, text, send, force, summary
            )
    except lock.Busy:
        summary["status"] = "busy"
        return summary


async def _round(pool, r, community, community_id, topic, text, send, force, summary):
    if not force:
        last = await audience.community_last_push_at(pool, community_id)
        if last is not None and _within(last, COMMUNITY_CAP_DAYS):
            summary["status"] = "community-capped"
            return summary

    members = await audience.members(pool, community_id)
    summary["members"] = len(members)

    recipients = []
    for session_id in members:
        try:
            if held := await _hold(r, session_id):
                summary[held].append(session_id)
            elif not force and await _capped(pool, session_id):
                summary["skipped_cap"].append(session_id)
            else:
                recipients.append(session_id)
        except Exception:
            # Redis สะดุดตอนถามถึงคนคนเดียว ต้องไม่ทำให้ทั้งชุมชนไม่ได้รับ
            # ของเดิมไม่มี try ตรงนี้ พิสูจน์มาแล้วว่าคนเดียวล้ม = ทั้งรอบตาย
            log.warning("เลือกผู้รับไม่สำเร็จ ข้ามคนนี้ session=%s", session_id, exc_info=True)
            summary["skipped_error"].append(session_id)

    # ใครผ่านด่านมาแล้วบ้าง — ตอบไว้ก่อนส่ง เพื่อให้ลองเปล่า ๆ (ไม่ส่งจริง) แล้ว
    # ยังเห็นได้ว่ารอบนี้จะไปถึงใคร ตัวเลขที่ต้องดูก่อนกดส่งจริงอยู่ตรงนี้
    summary["recipients"] = recipients
    if not recipients:
        return summary

    return summary | await _deliver(
        pool, r, recipients, topic, text, send, community_id, community
    )


async def _deliver(pool, r, recipients, topic, text, send, community_id, where) -> dict:
    """แต่งข้อความ (ถ้ายังไม่มี) → ส่ง → จดว่าทักใครไปแล้ว

    **หนึ่งรอบใช้ข้อความเดียวกันทุกคน** ไม่ได้แต่งใหม่รายคน เพราะเสียเงินเรียก
    โมเดลเท่าจำนวนคน เพื่อความต่างที่ไม่มีใครเห็น (ไม่มีใครเห็นข้อความของคนอื่น)
    """
    if text is None:
        text = await opening(topic, where)

    result = await send(recipients, text)

    # จดเฉพาะคนที่ถึงจริง — คนที่ส่งไม่ผ่านยังไม่เคยถูกทัก cap ไม่ควรนับเขา
    for session_id in result["sent"]:
        try:
            outreach_id = await audience.log_push(
                pool, session_id, topic, community_id, text
            )
            # ธงนี้คือสิ่งเดียวที่ทำให้ข้อความถัดไปของเขาถูกนับว่าเป็นคำตอบของเรา
            await r.set(_mode_key(session_id), outreach_id, ex=MODE_TTL_SECONDS)
        except Exception:
            # ทักไปแล้วแต่จดไม่ลง = อีกสัปดาห์เขาอาจโดนทักซ้ำ และคำตอบของเขา
            # จะถูกนับเป็นเรื่องที่เขาเดินมาเล่าเอง ยอมรับได้ แต่ต้องได้ยินเสียง
            log.exception("ส่งถึงแล้วแต่จดไม่ลง session=%s", session_id)

    return {"text": text, "sent": result["sent"], "failed": result["failed"]}


# ------------------------------------------------------------ ทางกลับ

# ธงว่า "เราทักคนนี้ไปและยังรอเขาตอบอยู่" อยู่ได้เท่าอายุใบที่คุยค้าง
# หมดอายุก่อนเขาตอบ = ใบนั้นลงเป็น source='user' ธรรมดา ยอมรับได้
# เสียแค่ป้ายบอกที่มา ไม่ได้เสียเรื่องที่เขาเล่า
MODE_TTL_SECONDS = draft.TTL_SECONDS


def _mode_key(session_id: str) -> str:
    return f"broadcast:mode:{session_id}"


async def source_of(pool: asyncpg.Pool, r: Redis, session_id: str) -> str:
    """ตานี้เป็นการตอบกลับข้อความที่เราทักไปไหม — คืน "broadcast" หรือ "user"

    **ตอบมาเลยนับว่าตอบ** ไม่มีปุ่มให้ตีความว่ารับหรือปฏิเสธ เพราะไม่มีปุ่ม
    เขาจะตอบว่าไม่มีปัญหาอะไรก็เป็นคำตอบ และเป็นคำตอบที่มีความหมายพอ ๆ กัน
    ส่วนคำถามที่ว่า "ทักไปแล้วได้เรื่องกลับมาไหม" ตอบด้วย outreach.report_id

    เขียนลง outreach ตรงนี้เลย ครั้งแรกครั้งเดียว (`mark_response` กันซ้ำให้)
    """
    outreach_id = await r.get(_mode_key(session_id))
    if outreach_id is None:
        return "user"

    try:
        await audience.mark_response(pool, int(outreach_id), "replied")
    except Exception:
        # จดไม่ลงไม่ควรทำให้เขาคุยกับบอทไม่ได้ — ตัวเลขสถิติสำคัญน้อยกว่าเรื่องที่เขาจะเล่า
        log.exception("จดว่าเขาตอบแล้วไม่สำเร็จ session=%s", session_id)

    return "broadcast"


async def link_report(pool: asyncpg.Pool, r: Redis, session_id: str, report_id: int) -> None:
    """ใบปิดแล้ว ผูกกลับไปที่การทักครั้งนั้นแล้วเก็บธงลง

    ตอบคำถามที่ของเดิมตอบไม่ได้เลย: ทักไป 100 คน ได้เรื่องกลับมากี่เรื่อง
    """
    outreach_id = await r.get(_mode_key(session_id))
    if outreach_id is None:
        return

    await audience.attach_report(pool, int(outreach_id), report_id)
    await r.delete(_mode_key(session_id))


# ------------------------------------------------------------ ยาม


async def _hold(r: Redis, session_id: str) -> str | None:
    """ทักคนนี้ตอนนี้ไม่ได้เพราะอะไร — None = ทักได้ ไม่งั้นคืนชื่อช่องในสรุป

    **`force` ข้ามทั้งสองด่านนี้ไม่ได้ ตั้งใจ** — cap 7 วันเป็นนโยบายกันสแปม
    ซึ่งยกเว้นได้ ส่วนสองอันนี้เป็นเรื่องของคนตรงหน้า ยกเว้นไม่ได้

    แต่**แยกกันรายงาน** เพราะบนหน้าจอมันคนละเรื่องกันสิ้นเชิง เดิมเขียนรวมเป็น
    "กำลังคุยค้างอยู่" อันเดียว คนที่เพิ่งคุยจบไปเมื่อกี้เลยอ่านแล้วคิดว่าระบบมั่ว
    — เพราะเขารู้ดีว่าบทสนทนาจบไปแล้ว **ข้อความที่ไม่ตรงความจริงทำให้คนไม่เชื่อ
    ด่านที่ถูกต้อง** แล้วไปหาทางข้ามมันแทนที่จะเข้าใจว่ามันกันอะไรอยู่
    """
    if await draft.load_all(r, session_id):
        # ใบยังค้าง = เขากำลังเล่าเรื่องให้เราฟังอยู่ ข้อความเราจะไปแทรกกลาง
        return "skipped_talking"

    if await draft.just_finished(r, session_id):
        # เล่าจบไปแล้วภายใน 30 นาที เรื่องเก็บเรียบร้อย ไม่มีอะไรค้าง
        # กันไว้เพราะมารยาท ทักซ้ำทันทีเหมือนบอทไม่ฟังที่เขาเพิ่งพูด
        # ปลดได้ที่ POST /api/broadcast/unblock ตอนทดสอบ
        return "skipped_recent"

    return None


async def clear_recent(r: Redis, session_id: str) -> dict:
    """ปลดป้าย "เพิ่งคุยจบ" ของคนนี้ ใช้ตอนทดสอบ

    **ปลดได้เฉพาะป้าย ไม่แตะใบที่ค้างอยู่** ป้ายนี้ปลดแล้วไม่มีอะไรหาย เรื่อง
    ที่เขาเล่าลงตารางไปตั้งแต่ตอนปิดใบแล้ว แต่ใบที่ยังค้างคือของที่ยังไม่ได้เก็บ
    ที่ไหนเลย ลบทิ้งเมื่อไหร่คือเสียเรื่องที่เขากำลังเล่าอยู่จริง ๆ
    """
    if await draft.load_all(r, session_id):
        return {"cleared": False, "reason": "talking"}

    await draft.clear_done(r, session_id)
    return {"cleared": True}


async def seconds_left(r: Redis, session_id: str) -> int:
    """ป้าย "เพิ่งคุยจบ" ของคนนี้เหลืออีกกี่วินาที — 0 ถ้าไม่ติดอะไร"""
    return await draft.done_seconds_left(r, session_id)


async def _capped(pool: asyncpg.Pool, session_id: str) -> bool:
    last = await audience.last_push_at(pool, session_id)
    return last is not None and _within(last, PERSON_CAP_DAYS)


def _within(moment, days: int) -> bool:
    """`moment` เพิ่งผ่านมาไม่เกินกี่วัน — เทียบด้วยนาฬิกาที่มี timezone เสมอ

    sent_at ใน Postgres เป็น timestamptz จึงมี timezone ติดมา เอาไปลบกับ
    datetime.now() เปล่า ๆ จะได้ TypeError ตอนรัน ไม่ใช่ตอนเขียน
    """
    return moment > datetime.now(timezone.utc) - timedelta(days=days)
