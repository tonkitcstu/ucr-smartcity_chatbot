"""ใครเป็นใคร — แกะ `Authorization` แล้วบอกว่าให้ผ่านไหม

รับสองแบบในด่านเดียวกัน เพราะคนเข้ามีสองพวกจริง ๆ:

    Authorization: Bearer <jwt>          ทีมแดชบอร์ด (เครื่องเรียกเครื่อง)
    Authorization: Basic  <user:pass>    คนในทีมเราที่เปิดจากเบราว์เซอร์

**JWT เราเป็นฝ่ายตรวจอย่างเดียว ไม่เคยเป็นคนออก** คนออกคือ backend ของทีม
แดชบอร์ด เราถือ SECRET_KEY ดอกเดียวกันแล้วแกะเอง ยกมาจาก `app/utils/auth.py`
บน branch main ทั้งดุ้น — รูปร่าง token เหมือนเดิมเป๊ะ (`sub`, `role`, HS256)
เพื่อให้เขาเรียกแบบเดิมได้โดยไม่ต้องแก้อะไร

ไฟล์นี้ไม่รู้จักเว็บเฟรมเวิร์กและไม่รู้จักรหัสสถานะ HTTP เหมือนไฟล์อื่นใน
services/ — มันบอกได้แค่ "ไม่มีกุญแจ" กับ "กุญแจผิด" ส่วนจะแปลเป็น 503 หรือ 401
เป็นเรื่องของ api/deps.py
"""

import base64
import binascii
import secrets

from jose import JWTError, jwt

from app.core.config import (
    ALGORITHM,
    DASHBOARD_PASSWORD,
    DASHBOARD_USER,
    SECRET_KEY,
)


class Locked(Exception):
    """ยังไม่ได้ตั้งกุญแจไว้เลย — ไม่มีทางเข้าได้ ไม่ว่าจะยื่นอะไรมา

    **นี่ไม่ใช่ความผิดของคนที่ยิงเข้ามา** เป็นความผิดของคนตั้งเครื่อง
    เลยแยกจาก Denied เพื่อให้ข้อความบอกได้ตรง ๆ ว่าต้องไปเติมอะไรใน .env
    """


class Denied(Exception):
    """ยื่นกุญแจมาแล้วแต่ไม่ผ่าน (หรือไม่ได้ยื่นมาเลย)"""


def read_jwt(token: str) -> dict:
    """แกะ token ของทีมแดชบอร์ด คืน `{"username", "role"}`

    ตรงกับ `get_current_user` ของเดิมทุกบรรทัด รวมทั้งเงื่อนไข "ไม่มี sub = ไม่ผ่าน"
    เราไม่มีตารางผู้ใช้ของแดชบอร์ด ตัวตนจึงมาจากใน token เองล้วน ๆ
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise Denied("token ใช้ไม่ได้") from exc

    username = payload.get("sub")
    if username is None:
        raise Denied("token ไม่มี sub")

    return {"username": username, "role": payload.get("role")}


def read_basic(blob: str) -> dict:
    """แกะ `Basic <base64>` เทียบกับรหัสใน .env คืน `{"username", "role"}`

    เทียบด้วย `compare_digest` ทั้งชื่อและรหัส **ไม่ใช่ `==`** — `==` หยุดเทียบ
    ทันทีที่เจอตัวอักษรตัวแรกที่ต่าง เวลาที่ใช้จึงบอกใบ้ว่าเดาถูกไปกี่ตัวแล้ว
    """
    try:
        raw = base64.b64decode(blob, validate=True).decode("utf-8")
        user, _, password = raw.partition(":")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise Denied("รหัสที่ส่งมาอ่านไม่ออก") from exc

    ok_user = secrets.compare_digest(user, DASHBOARD_USER)
    ok_password = secrets.compare_digest(password, DASHBOARD_PASSWORD or "")
    if not (ok_user and ok_password):
        raise Denied("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")

    # role ให้เท่ากับ JWT ฝั่งที่เป็น admin เพราะคนที่ถือรหัสใน .env คือคนของเรา
    return {"username": user, "role": "admin"}


def identify(header: str | None) -> dict:
    """`Authorization` ดิบ ๆ → ตัวตน  โยน Locked/Denied ถ้าไม่ผ่าน

    **ยอมให้ตั้งไว้อย่างเดียวก็เข้าได้** — เครื่อง dev ตั้งแต่รหัสผ่านก็พอ
    ส่วน prod ที่ยังไม่ได้คุยกับทีมแดชบอร์ดก็ยังล็อกหน้าเว็บของตัวเองได้
    ที่ห้ามคือ **ไม่ตั้งอะไรเลยแล้วเปิดโล่ง** ซึ่งคือบั๊กที่ #139 มาแก้พอดี
    """
    if not SECRET_KEY and not DASHBOARD_PASSWORD:
        raise Locked(
            "ยังไม่ได้ตั้ง DASHBOARD_PASSWORD หรือ SECRET_KEY ใน .env — ปิดไว้ก่อน"
        )

    if not header:
        raise Denied("ต้องแนบ Authorization มาด้วย")

    scheme, _, blob = header.partition(" ")
    scheme = scheme.lower()

    if scheme == "bearer":
        if not SECRET_KEY:
            raise Denied("เครื่องนี้ยังไม่ได้ตั้ง SECRET_KEY จึงตรวจ token ไม่ได้")
        return read_jwt(blob.strip())

    if scheme == "basic":
        if not DASHBOARD_PASSWORD:
            raise Denied("เครื่องนี้ยังไม่ได้ตั้ง DASHBOARD_PASSWORD")
        return read_basic(blob.strip())

    raise Denied("รองรับแค่ Bearer กับ Basic")
