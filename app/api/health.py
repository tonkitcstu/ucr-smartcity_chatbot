"""ทางเดียวที่เปิดโล่งนอกจาก webhook — "แอปยังหายใจอยู่ไหม"

เคยอยู่ใน api/dev.py แต่ต้องย้ายออกมาตอนล็อกประตู (issue #139) เพราะ dev.py
ทั้งไฟล์ไม่ขึ้น prod แล้ว ส่วนตัวเช็คสุขภาพต้องเรียกได้เสมอ ไม่งั้นตัวมอนิเตอร์
กับ load balancer จะอ่านว่าแอปตายทั้งที่แอปสบายดี

**ห้ามใส่อะไรที่บอกความลับลงในนี้** ใครก็ยิงได้ ตอบแค่ว่าต่อ Redis ติดไหม
ไม่บอกเวอร์ชัน ไม่บอกจำนวนใบ ไม่บอกว่ามีใครคุยค้างอยู่กี่คน
"""

from fastapi import APIRouter, Depends
from redis.asyncio import Redis

from app.api.deps import get_redis

router = APIRouter(prefix="/api")


@router.get("/health")
async def health(r: Redis = Depends(get_redis)):
    return {"status": "OK", "redis": await r.ping()}
