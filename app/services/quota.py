"""โควตา — เขียว/เหลือง/แดง

ตัวที่พังไม่ใช่ค่าใช้จ่าย แต่คือ **ความเงียบ** คนเดียวหรือ retry loop เดียวดูดงบ
ที่ใช้ร่วมกันจนหมด แล้วบอทเงียบทั้งชุมชนโดยที่ไม่มีใครรู้ว่าเกิดอะไรขึ้น

cap ธรรมดาตัด "คนที่เพิ่งจะเริ่มเล่า" กับ "คนที่เล่าไปครึ่งเรื่องแล้ว" เท่ากัน
ซึ่งแปลว่าเสียใบที่เขาอุตส่าห์เล่ามาครึ่งทาง สามโซนนี้มีไว้แยกสองคนนั้นออกจากกัน

    🟢 เขียว   ผ่านหมด
    🟡 เหลือง  คนใหม่รอก่อน · **คนที่เล่าค้างอยู่เล่าต่อจนจบได้**
    🔴 แดง     ไม่คุยต่อแล้ว — ใบที่ค้างอยู่ปิดเก็บเท่าที่เล่ามา ไม่ทิ้ง

สัญญาณว่า "เล่าค้างอยู่" ไม่ได้สร้างใหม่ ใช้ `draft.load_all()` ตัวเดียวกับที่
`broadcast._hold()` ใช้กันไม่ให้ทักคนกลางบทสนทนา

**สิ่งที่โซนเหลืองสัญญาไว้ ต้องมีงบรองรับจริง** ไม่งั้นคนที่เล่าค้างจะวิ่งไปชนแดง
กลางทางอยู่ดี = เสียใบเหมือนไม่มีโซนเหลือง แถมหลอกเขาไปหนึ่งรอบ ตัวเลขที่กันไว้
อยู่ที่ QUOTA_YELLOW_* ใน core/config.py พร้อมที่มาของเลข

ไฟล์นี้ไม่รู้จักเว็บเฟรมเวิร์กและไม่รู้จัก LINE — Redis กับตัวเลขล้วน
"""

import datetime as dt
import logging

from redis.asyncio import Redis

from app.clients import llm
from app.core.config import (
    QUOTA_DAY_CALLS,
    QUOTA_DAY_TOKENS,
    QUOTA_DRAFT_TURNS,
    QUOTA_ENABLED,
    QUOTA_LIMIT_BY,
    QUOTA_RUSH_SECONDS,
    QUOTA_RUSH_TURNS,
    QUOTA_USER_TURNS,
    QUOTA_USER_YELLOW_TURNS,
    QUOTA_WINDOW_CALLS,
    QUOTA_WINDOW_HOURS,
    QUOTA_WINDOW_TOKENS,
    QUOTA_YELLOW_CALLS,
    QUOTA_YELLOW_TOKENS,
)
from app.services import draft

log = logging.getLogger(__name__)

GREEN = "green"
YELLOW = "yellow"
RED = "red"

# เวลาไทยเสมอ — หน้าต่างต้องรีเซ็ต 00/06/12/18 ตามนาฬิกาที่ชาวบ้านใช้
# ไม่ใช่ตามนาฬิกาเครื่อง (บนเซิร์ฟเวอร์มักเป็น UTC ซึ่งเพี้ยนไป 7 ชั่วโมง)
_BANGKOK = dt.timezone(dt.timedelta(hours=7))

# ข้อความตอนแดง — **hardcode เส้นเดียวของโปรเจกต์ และตั้งใจให้เป็นแบบนั้น**
#
# ตรงนี้เรียกโมเดลไม่ได้ เพราะการเรียกโมเดลไม่ได้คือสาเหตุที่มาถึงตรงนี้
# มันขัดกับกฎ "คำถามเป็นของ AI" ตรง ๆ เลยเขียนไว้ให้เห็นชัดว่ารู้ตัว
# ไม่ใช่ string ที่หลุดเข้ามาเงียบ ๆ — ที่อื่นห้ามเพิ่มแบบนี้อีก
RED_NOTICE = (
    "ขอโทษนะคะ วันนี้น้องเมืองคุยมาเยอะจนต้องพักแล้วค่ะ "
    "เดี๋ยวกลับมาใหม่ ไว้มาเล่าให้ฟังต่อได้นะคะ 🙏"
)

# แดงตอนเขากำลังเล่าค้าง — **เราปิดใบเก็บเรื่องเขาไว้แล้ว ต้องบอกเขาด้วย**
#
# เจอจากการเทสต์จริง: เดิมใช้ข้อความเดียวกับข้างบน ซึ่งบอกว่า "ไว้มาเล่าต่อ"
# ทั้งที่ใบถูกปิดไปแล้ว เขาจะกลับมาเล่าต่อจากตรงไหนก็ไม่ได้ และไม่รู้ด้วยซ้ำว่า
# เรื่องที่เล่าไปครึ่งทางนั้นถึงมือเราแล้ว — ไฟล์ api/line.py มีกฎข้อนี้อยู่ก่อนแล้ว
# ว่าอย่าปล่อยให้เขาเดินจากไปโดยเข้าใจสถานะผิด
RED_SAVED_NOTICE = (
    "ขอบคุณมากนะคะ น้องเมืองจดเรื่องที่เล่ามาไว้ให้แล้วค่ะ "
    "วันนี้คุยมาเยอะจนต้องขอพักก่อน ไว้มาเล่าเรื่องอื่นให้ฟังใหม่ได้นะคะ 🙏"
)

# ข้อความตอนเหลืองให้ AI แต่งไว้ล่วงหน้าตอนยังเขียว แล้วแช่ไว้ตรงนี้
# **AI ยังเป็นคนเขียนอยู่ แค่เขียนก่อน** — ไม่ขัดกฎเหมือนตัวแดง
_NOTICE_KEY = "quota:notice"
_NOTICE_TTL = 24 * 60 * 60

_NOTICE_PROMPT = (
    "คุณคือ 'น้องเมือง' บอทที่ชวนคนในชุมชนเล่าเรื่องสภาพแวดล้อมแถวบ้าน\n"
    "ตอนนี้ระบบใกล้เต็มโควตาของวัน ยังรับคนที่เล่าค้างอยู่ให้เล่าจบได้ "
    "แต่ยังเริ่มเรื่องใหม่ไม่ได้\n\n"
    "เขียนข้อความสั้น ๆ บอกเขาว่าตอนนี้ยังรับเรื่องใหม่ไม่ได้ "
    "ชวนให้กลับมาเล่าอีกทีในอีกไม่กี่ชั่วโมง\n"
    "- ไม่เกิน 2 ประโยค\n"
    "- สุภาพ อบอุ่น ลงท้ายด้วยค่ะ\n"
    "- ห้ามพูดถึงคำว่าโควตา ระบบ เซิร์ฟเวอร์ AI หรือตัวเลขใด ๆ\n"
    "- ตอบมาเฉพาะตัวข้อความ ไม่ต้องมีอัญประกาศครอบ"
)

# ถ้า AI ยังไม่เคยแต่งให้ (เพิ่งเปิดแอป / Redis โดนล้าง) ใช้ตัวแดงไปก่อน
# ดีกว่าเงียบใส่เขา และเป็นทางที่ควรเกิดน้อยมาก


def _now() -> dt.datetime:
    return dt.datetime.now(_BANGKOK)


def _day_key() -> str:
    return _now().date().isoformat()


def _window_key() -> str:
    """`2026-08-08:2` — ช่องที่เท่าไหร่ของวัน นับจากเที่ยงคืนเวลาไทย

    ใช้ช่องตายตัวไม่ใช่ sliding window เพราะ sliding ต้องใช้ sorted set
    ส่วนตัวนี้เป็น INCR + TTL ล้วนตามที่ตั้งใจไว้ และ**บอกได้ว่าจะรีเซ็ตกี่โมง**
    ซึ่งสำคัญกว่าความแม่นระดับวินาที เวลาต้องอธิบายให้คนอื่นฟัง
    """
    now = _now()
    hours = QUOTA_WINDOW_HOURS or 6
    return f"{now.date().isoformat()}:{now.hour // hours}"


def seconds_to_window_reset() -> int:
    """อีกกี่วินาทีหน้าต่างถัดไปจะเปิด — ไว้บอกเขาว่ารอถึงเมื่อไหร่"""
    now = _now()
    hours = QUOTA_WINDOW_HOURS or 6
    nxt = (now.hour // hours + 1) * hours

    if nxt >= 24:
        start = (now + dt.timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    else:
        start = now.replace(hour=nxt, minute=0, second=0, microsecond=0)

    return max(0, int((start - now).total_seconds()))


async def _count(r: Redis, key: str) -> int:
    """อ่านตัวนับ — อ่านไม่ได้ให้ถือว่า 0

    **ตัวนับพังต้องไม่แปลว่าห้ามคุย** Redis กระตุกแล้วบอทเงียบทั้งชุมชน
    คือความพังที่ใหญ่กว่าปัญหาที่ไฟล์นี้แก้
    """
    try:
        return int(await r.get(key) or 0)
    except Exception:
        log.warning("อ่านตัวนับโควตาไม่ได้ key=%s ถือว่า 0", key)
        return 0


def _by_tokens() -> bool:
    return QUOTA_LIMIT_BY in ("both", "tokens")


def _by_calls() -> bool:
    return QUOTA_LIMIT_BY in ("both", "requests")


def _zone_of(used: int, ceiling: int, yellow_gap: int) -> str:
    """โซนของตัวนับตัวเดียว — เหลืองคือ "เหลืองบน้อยกว่าที่กันไว้ให้คนเล่าจบ" """
    if ceiling <= 0:
        return GREEN
    if used >= ceiling:
        return RED
    if used >= max(0, ceiling - yellow_gap):
        return YELLOW
    return GREEN


def _worst(zones: list[str]) -> str:
    if RED in zones:
        return RED
    if YELLOW in zones:
        return YELLOW
    return GREEN


async def check(r: Redis, session_id: str) -> dict:
    """โซนของตานี้ คืน `{"zone", "reason"}`

    `reason` มีไว้ให้ log กับเลือกข้อความ ไม่ได้ให้ชาวบ้านอ่าน

    **เรียกก่อนคุย** ส่วนการบวกตัวนับเรียกทีหลังด้วย spend() เพราะก่อนคุยยังไม่รู้
    ว่าตานี้จะกินกี่ครั้งกี่ token
    """
    if not QUOTA_ENABLED:
        return {"zone": GREEN, "reason": None}

    day, window = _day_key(), _window_key()
    checks: list[tuple[str, str]] = []

    # ── ชั้นที่อยู่นอกระบบโซน ตั้งใจ ────────────────────────────────────────
    #
    # บทสนทนาที่ค้างวนไม่จบ **คือ "คนที่กำลังเล่าค้างอยู่" พอดี** ถ้าเอาสองชั้นนี้
    # เข้าโซน โซนเหลืองจะไปปกป้องตัวที่ควรฆ่า เลยตัดสินแยกและตัดสินเป็นแดงตรง ๆ
    if QUOTA_DRAFT_TURNS > 0:
        if await _count(r, f"quota:draft:{session_id}") >= QUOTA_DRAFT_TURNS:
            return {"zone": RED, "reason": "draft"}

    if QUOTA_RUSH_TURNS > 0:
        if await _count(r, f"quota:rush:{session_id}") >= QUOTA_RUSH_TURNS:
            return {"zone": RED, "reason": "rush"}

    # ── ระบบ ────────────────────────────────────────────────────────────────
    if _by_calls():
        checks.append((
            _zone_of(
                await _count(r, f"quota:sys:day:{day}:calls"),
                QUOTA_DAY_CALLS,
                QUOTA_YELLOW_CALLS,
            ),
            "system-day-calls",
        ))
        checks.append((
            _zone_of(
                await _count(r, f"quota:sys:win:{window}:calls"),
                QUOTA_WINDOW_CALLS,
                QUOTA_YELLOW_CALLS,
            ),
            "system-window-calls",
        ))

    if _by_tokens():
        checks.append((
            _zone_of(
                await _count(r, f"quota:sys:day:{day}:tokens"),
                QUOTA_DAY_TOKENS,
                QUOTA_YELLOW_TOKENS,
            ),
            "system-day-tokens",
        ))
        checks.append((
            _zone_of(
                await _count(r, f"quota:sys:win:{window}:tokens"),
                QUOTA_WINDOW_TOKENS,
                QUOTA_YELLOW_TOKENS,
            ),
            "system-window-tokens",
        ))

    # ── ต่อคน: นับเป็น "ตา" ไม่ใช่ token ────────────────────────────────────
    # เหตุผลอยู่ใน core/config.py — ชาวบ้านคุมไม่ได้ว่าตาเขากิน token เท่าไหร่
    if QUOTA_USER_TURNS > 0:
        checks.append((
            _zone_of(
                await _count(r, f"quota:user:{session_id}:{window}"),
                QUOTA_USER_TURNS,
                max(0, QUOTA_USER_TURNS - QUOTA_USER_YELLOW_TURNS),
            ),
            "user",
        ))

    zone = _worst([z for z, _ in checks])
    reason = next((name for z, name in checks if z == zone), None)

    return {"zone": zone, "reason": reason if zone != GREEN else None}


async def allowed(r: Redis, session_id: str) -> dict:
    """โซน + ตัดสินให้เลยว่าตานี้คุยได้ไหม โดยดูว่าเขาเล่าค้างอยู่หรือเปล่า

    คืน `{"zone", "reason", "go", "mid_draft"}`

    - เขียว           go=True
    - เหลือง + ค้างอยู่ go=True   ← หัวใจของทั้งไฟล์
    - เหลือง + คนใหม่  go=False
    - แดง             go=False (คนที่ค้างอยู่ mid_draft=True คนเรียกต้องปิดใบเก็บให้เขา)
    """
    state = await check(r, session_id)
    zone = state["zone"]

    if zone == GREEN:
        return state | {"go": True, "mid_draft": False}

    try:
        mid_draft = bool(await draft.load_all(r, session_id))
    except Exception:
        # อ่านใบค้างไม่ได้ **ให้ผ่านไว้ก่อน** — เดาผิดทางนี้แค่ใช้งบเกินนิดหน่อย
        # เดาผิดอีกทางคือตัดคนที่เล่าไปครึ่งเรื่องแล้วทิ้ง
        log.warning("อ่านใบค้างไม่ได้ session=%s ปล่อยผ่าน", session_id)
        return state | {"go": True, "mid_draft": True}

    if zone == YELLOW:
        return state | {"go": mid_draft, "mid_draft": mid_draft}

    return state | {"go": False, "mid_draft": mid_draft}


async def spend(r: Redis, session_id: str, used: dict) -> None:
    """บวกตัวนับหลังคุยจบหนึ่งตา — `used` คือ `{"calls", "tokens"}` จาก survey.reply()

    ทุกตัวเป็น INCR + EXPIRE ล้วน ไม่มีอะไรต้องเก็บกวาด กุญแจหมดอายุเอง

    ล้มตรงนี้ไม่ควรทำให้ตาที่คุยไปแล้วพัง — ตอบเขาไปแล้ว บวกไม่ทันก็แค่นับขาด
    """
    if not QUOTA_ENABLED:
        return

    calls = int(used.get("calls") or 0)
    tokens = int(used.get("tokens") or 0)

    day, window = _day_key(), _window_key()

    # หน้าต่างของวันถัดไปเป็นคนละกุญแจอยู่แล้ว TTL แค่กันไม่ให้ค้างใน Redis
    day_ttl = 48 * 60 * 60
    window_ttl = (QUOTA_WINDOW_HOURS or 6) * 60 * 60 * 2

    try:
        async with r.pipeline(transaction=False) as pipe:
            if calls:
                pipe.incrby(f"quota:sys:day:{day}:calls", calls)
                pipe.expire(f"quota:sys:day:{day}:calls", day_ttl)
                pipe.incrby(f"quota:sys:win:{window}:calls", calls)
                pipe.expire(f"quota:sys:win:{window}:calls", window_ttl)

            if tokens:
                pipe.incrby(f"quota:sys:day:{day}:tokens", tokens)
                pipe.expire(f"quota:sys:day:{day}:tokens", day_ttl)
                pipe.incrby(f"quota:sys:win:{window}:tokens", tokens)
                pipe.expire(f"quota:sys:win:{window}:tokens", window_ttl)

            # ตาของคน นับทุกตาที่ได้คุย ไม่ว่าจะกินโมเดลกี่ครั้ง
            pipe.incr(f"quota:user:{session_id}:{window}")
            pipe.expire(f"quota:user:{session_id}:{window}", window_ttl)

            pipe.incr(f"quota:rush:{session_id}")
            pipe.expire(f"quota:rush:{session_id}", QUOTA_RUSH_SECONDS)

            pipe.incr(f"quota:draft:{session_id}")
            pipe.expire(f"quota:draft:{session_id}", draft.TTL_SECONDS)

            await pipe.execute()
    except Exception:
        log.warning("บวกตัวนับโควตาไม่สำเร็จ session=%s", session_id, exc_info=True)


async def clear_draft(r: Redis, session_id: str) -> None:
    """ปิดใบแล้วเริ่มนับใหม่ — ไม่งั้นคนที่เล่าสองเรื่องติดกันจะโดน cap ของใบแรกค้างมา"""
    try:
        await r.delete(f"quota:draft:{session_id}")
    except Exception:
        log.warning("ล้างตัวนับต่อใบไม่สำเร็จ session=%s", session_id)


async def notice(r: Redis, zone: str, saved: bool = False) -> str:
    """ข้อความที่ชาวบ้านได้เห็นตอนถูกกั้น

    แดง = ตัวคงที่ (เรียกโมเดลไม่ได้แล้ว) · เหลือง = ตัวที่ AI แต่งไว้ตอนยังเขียว

    `saved=True` เมื่อเพิ่งปิดใบเก็บเรื่องเขาไว้ — ต้องบอกเขา ไม่ใช่แค่บอกว่าพัก
    """
    if zone == RED:
        return RED_SAVED_NOTICE if saved else RED_NOTICE

    try:
        cached = await r.get(_NOTICE_KEY)
    except Exception:
        cached = None

    if cached:
        return cached.decode() if isinstance(cached, bytes) else str(cached)

    return RED_NOTICE


async def refresh_notice(r: Redis) -> bool:
    """ให้ AI แต่งข้อความโซนเหลืองเก็บไว้ — **เรียกตอนยังเขียวเท่านั้น**

    เรียกทุกตาก็ได้ ข้างในเช็คเองว่ามีของสดอยู่แล้วหรือยัง วันละครั้งพอ
    ต้นทุนวันละ 1 call แลกกับการไม่ต้อง hardcode ข้อความอีกหนึ่งเส้น
    """
    try:
        if await r.exists(_NOTICE_KEY):
            return False
    except Exception:
        return False

    try:
        text, _used = await llm.chat([{"role": "user", "content": _NOTICE_PROMPT}])
    except Exception:
        log.warning("แต่งข้อความโซนเหลืองไม่สำเร็จ ใช้ตัวสำรองไปก่อน", exc_info=True)
        return False

    # โมเดลชอบใส่อัญประกาศคร่อมเวลาถูกสั่งให้ "เขียนข้อความ" — ลอกลีลาจาก broadcast.py
    text = (text or "").strip().strip('"').strip("“”").strip()
    if not text:
        return False

    try:
        await r.set(_NOTICE_KEY, text, ex=_NOTICE_TTL)
    except Exception:
        return False

    return True
