from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import JSONResponse
import traceback
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from linebot.v3 import WebhookParser
from linebot.v3.messaging import Configuration, AsyncApiClient, AsyncMessagingApi
from linebot.v3.webhooks import MessageEvent
from linebot.v3.exceptions import InvalidSignatureError

from app.config import CHANNEL_SECRET, CHANNEL_ACCESS_TOKEN, SURVEYS_DIR
from app.database import engine, Base, get_db
from app.handlers.message_handler import route_message_event
from app.utils.survey_loader import survey_manager
from app.routes.dashboard import router as dashboard_router
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from mangum import Mangum
import os

# Detect if running in AWS Lambda
is_lambda = os.environ.get("AWS_LAMBDA_FUNCTION_NAME") is not None
UPLOAD_DIR = "/tmp/uploads" if is_lambda else "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# NEW: The "lifespan" context manager is how FastAPI runs code BEFORE the server starts accepting requests
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. จัดการ Database
    try:
        async with engine.begin() as conn:
            # Enable PostGIS extension if not exists
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
            
            # Create tables if not exist
            await conn.run_sync(Base.metadata.create_all)
            
            print("✅ Database tables checked/created with Bangkok timezone defaults!")
    except Exception as e:
        print(f"⚠️ Database initialization warning (likely concurrent start): {e}")

    # 2. จัดการโหลด Survey JSON ทั้งโฟลเดอร์
    try:
        # ใช้ฟังก์ชันใหม่ที่เราเพิ่งสร้าง ชี้ไปที่โฟลเดอร์ SURVEYS_DIR
        survey_manager.load_all_surveys_in_directory(SURVEYS_DIR)
        print("✅ All survey JSONs loaded successfully during startup!")
    except Exception as e:
        print(f"❌ Failed to load survey JSONs: {e}")
        # ถ้าโหลดไม่ผ่าน (เช่น โฟลเดอร์ไม่มี หรือไฟล์ JSON พัง) ให้หยุดเซิร์ฟเวอร์ไปเลย
        raise e
        
    yield
    # (Anything below the yield runs when the server is shutting down)

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:4200")
ENV = os.getenv("ENV", "development")

# Disable Swagger UI and ReDoc in production
docs_url = None if ENV == "production" else "/docs"
redoc_url = None if ENV == "production" else "/redoc"

app = FastAPI(lifespan=lifespan, docs_url=docs_url, redoc_url=redoc_url)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:4200"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(dashboard_router)

# DEV-ONLY: mock dashboard for eyeballing the API during development.
# Never registered in production — no /mock or /mock/token there.
if ENV != "production":
    from app.routes.mock_dashboard import router as mock_router
    app.include_router(mock_router)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # Full detail is logged for us only — never returned to the caller.
    print(f"Unhandled Exception: {exc}\n{traceback.format_exc()}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error"}
    )

@app.get("/api/health")
async def health_check():
    return {"status": "ok"}

# Mount Static Files
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
parser = WebhookParser(CHANNEL_SECRET)

# Notice how the Dependency now asks for an AsyncSession
@app.post("/callback")
async def callback(request: Request, db: AsyncSession = Depends(get_db)):
    signature = request.headers.get('x-line-signature', '')
    body = await request.body()
    body_text = body.decode('utf-8')

    try:
        events = parser.parse(body_text, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    async with AsyncApiClient(configuration) as api_client:
        line_bot_api = AsyncMessagingApi(api_client)

        for event in events:
            if isinstance(event, MessageEvent):
                await route_message_event(event, line_bot_api, db)

    return 'OK'

handler = Mangum(app)