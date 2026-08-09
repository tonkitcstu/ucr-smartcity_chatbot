import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import broadcast, dashboard, dev, health, line
from app.clients import db
from app.clients import redis as redis_client
from app.core.config import CORS_ORIGINS, DEV_ROUTES_ENABLED
from app.services import sweeper


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- startup ---
    app.state.redis = redis_client.create_client()
    await app.state.redis.ping()
    app.state.db = await db.create_pool()
    # ตาข่ายรองรับ เก็บใบที่ใกล้หมดอายุก่อนหาย — ดูเหตุผลใน services/sweeper.py
    sweep = asyncio.create_task(sweeper.run_forever(app.state.redis, app.state.db))
    print("app opened")
    try:
        yield
    finally:
        # --- shutdown ---
        sweep.cancel()
        await app.state.db.close()
        await app.state.redis.aclose()
        print("app closed")


# **ปิดของที่ FastAPI แถมมาให้ทิ้งทั้งหมด** /docs /redoc /openapi.json ของเดิม
# แจกแผนที่ทุก route ทุกพารามิเตอร์ให้คนที่ไม่มีกุญแจอ่าน และตรงนี้ล็อกมันไม่ได้
# (main.py มี route เองไม่ได้ — กฎข้อ 4) ของทดแทนที่มีกุญแจอยู่ใน api/dev.py
# ที่ /api/docs กับ /api/openapi.json ขึ้นพร้อม DEV_ROUTES_ENABLED เหมือนเดิม
app = FastAPI(
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# เบราว์เซอร์ของทีมแดชบอร์ดอยู่คนละ origin กับเรา ไม่ประกาศไว้เขายิงไม่ถึง
# `allow_credentials` ต้องเปิด เพราะเขาแนบ Authorization มาทุกครั้ง
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(line.router)
app.include_router(health.router)
app.include_router(dashboard.router)
app.include_router(broadcast.router)

# **ประตูที่กว้างที่สุดในโปรเจกต์ ต่อเข้าเฉพาะตอนสั่งเปิดเท่านั้น** (issue #139)
# ข้างในมี GET /api/reports (ใบทั้งตารางพร้อมพิกัดบ้าน), DELETE /api/survey/draft
# (ล้างใบที่คนกำลังเล่าค้างอยู่) และสามทางที่เผา quota โมเดลได้ฟรี
if DEV_ROUTES_ENABLED:
    app.include_router(dev.router)
