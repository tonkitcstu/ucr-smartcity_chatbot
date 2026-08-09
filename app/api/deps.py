"""Shared FastAPI dependencies."""

import asyncpg
from fastapi import Depends, Header, HTTPException, Request
from redis.asyncio import Redis

from app.services import auth


def get_redis(request: Request) -> Redis:
    """The Redis client created in the lifespan."""
    return request.app.state.redis


def get_db(request: Request) -> asyncpg.Pool:
    """The Postgres pool created in the lifespan."""
    return request.app.state.db


# ให้เบราว์เซอร์เด้งช่องกรอกรหัสเอง — ขาดหัวนี้ไปคนเปิด /dashboard จะเห็นแค่
# หน้าขาว 401 โดยไม่มีที่ให้พิมพ์อะไร
_ASK = {"WWW-Authenticate": 'Basic realm="ucr"'}


def guard(authorization: str | None = Header(default=None)) -> dict:
    """ด่านหน้าของทุก route ที่ไม่ใช่ webhook — แปะระดับ router ไม่ใช่ทีละทาง

    แปะระดับ router **ตั้งใจ** เพราะแบบทีละทางคือแบบที่ลืมได้ เพิ่ม route ใหม่
    วันหลังแล้วลืมใส่ = รูโหว่เงียบ ๆ ที่ไม่มีอะไรเตือน

    คืนตัวตนออกมาให้ route ที่อยากรู้ว่าใครเรียก (`Depends(guard)`) ส่วน route
    ที่ไม่สนใจก็ปล่อยผ่านไปเฉย ๆ
    """
    try:
        return auth.identify(authorization)
    except auth.Locked as exc:
        # 503 ไม่ใช่ 401 — ยื่นรหัสมาถูกก็ยังเข้าไม่ได้ ปัญหาอยู่ที่เครื่อง ไม่ใช่ที่คน
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except auth.Denied as exc:
        raise HTTPException(status_code=401, detail=str(exc), headers=_ASK) from exc


def require_admin(who: dict = Depends(guard)) -> dict:
    """ยกมาจาก `get_current_admin` เดิม — ยังไม่มี route ไหนเรียก เก็บไว้ให้ครบคู่

    **`= Depends(guard)` ตรงนั้นห้ามหาย** เขียนเป็น `who: dict` เฉย ๆ แล้วโค้ดจะ
    ยังรันได้ แต่ FastAPI จะอ่านว่า `who` คือ JSON body ที่ผู้เรียกต้องส่งมาเอง
    ผลคือได้ 422 ขอ body **โดยไม่เคยเช็ค role เลยสักครั้ง** — ล้มด้วยเหตุผลผิด
    แล้วคนจะไปไล่หาบั๊กผิดที่ (เขียนพลาดแบบนี้มาแล้วรอบหนึ่ง ยิงเทสถึงเจอ)
    """
    if who.get("role") != "admin":
        raise HTTPException(status_code=403, detail="สิทธิ์ไม่พอ")
    return who
