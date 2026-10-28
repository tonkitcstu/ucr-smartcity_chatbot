import os
from datetime import time
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")


def _flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


# เวลาในรูป "HH:MM" เช่น "01:00"
def _time(name: str, default: str) -> time:
    return time.fromisoformat(os.getenv(name) or default)


DATABASE_URL = os.getenv("DATABASE_URL")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
API_ENDPOINT = os.getenv(
    "API_ENDPOINT", "https://generativelanguage.googleapis.com/v1beta/openai/"
)
REASONING_EFFORT = os.getenv("REASONING_EFFORT", "high").strip().lower()

# worker: รอเงียบกี่วินาทีก่อนตอบ · ปิดได้ (test เรียก run_chat เอง)
SILENCE_SECONDS = float(os.getenv("SILENCE_SECONDS") or 3)
WORKER_ENABLED = os.getenv("WORKER_ENABLED", "true").strip().lower() in ("1", "true", "yes")
UPLOADS_DIR = Path(os.getenv("UPLOADS_DIR") or BASE_DIR / "uploads")

# sweeper: ปิดใบที่เงียบเกินกี่นาที · กวาดทุกกี่วินาที · เปิดด้วย WORKER_ENABLED ตัวเดียวกับ worker
# 2 ชั่วโมง (Idea 2026-10-23) · ใบปิดแล้วตัววิเคราะห์จึงเริ่ม รายงานขึ้นแดชบอร์ดหลังเงียบครบเวลานี้
CLOSE_AFTER_MINUTES = _int("CLOSE_AFTER_MINUTES", 120)
SWEEP_EVERY_SECONDS = _int("SWEEP_EVERY_SECONDS", 60)

# กุญแจที่ทีมแดชบอร์ดแนบมาใน Authorization: Bearer <กุญแจ> · ไม่ตั้ง = ทุกเส้นใต้ /api/dashboard ตอบ 503
DASHBOARD_API_KEY = os.getenv("DASHBOARD_API_KEY")
CORS_ORIGINS = [
    origin.strip().rstrip("/")
    for origin in (os.getenv("CORS_ORIGINS") or "").split(",")
    if origin.strip()
]

# ทักผู้แจ้งไปก่อนเมื่อพยากรณ์บอกว่าฝนจะตก · ค่าตั้งต้นปิด เพราะเปิดแล้วส่งข้อความหาผู้แจ้งจริง
BROADCAST_ENABLED = _flag("BROADCAST_ENABLED")
# ที่อยู่ไฟล์พยากรณ์รายวันที่ Lambda อัปโหลด · {date} แทนด้วย YYYY-MM-DD · ว่าง = ใช้ mock_forecast.json
FORECAST_URL = os.getenv("FORECAST_URL", "").strip()
# เวลาไทยทั้งหมด · อ่านพยากรณ์ตั้งแต่ BROADCAST_FETCH_AT เพราะทีม data อัปโหลดพยากรณ์ของวันใหม่ตอนตี 1
# ทักตั้งแต่ BROADCAST_SEND_AT · ถึง BROADCAST_SEND_UNTIL แล้วยังไม่ได้ทัก วันนั้นไม่ทักแล้ว ไม่ส่งข้อความตอนดึก
BROADCAST_FETCH_AT = _time("BROADCAST_FETCH_AT", "01:00")
BROADCAST_SEND_AT = _time("BROADCAST_SEND_AT", "08:00")
BROADCAST_SEND_UNTIL = _time("BROADCAST_SEND_UNTIL", "20:00")
# ตัวทักตื่นมาดูเวลาทุกกี่วินาที
BROADCAST_CHECK_SECONDS = _int("BROADCAST_CHECK_SECONDS", 60)
# ใบที่บอททักไปก่อน รอผู้แจ้งตอบกี่ชั่วโมงก่อนปิดใบ · ตอบแล้วนับแบบใบปกติ (CLOSE_AFTER_MINUTES)
BROADCAST_WAIT_HOURS = _int("BROADCAST_WAIT_HOURS", 24)
# ทักวันละไม่เกินกี่คน สุ่มเลือก · LINE แบบฟรีส่ง push ได้เดือนละ 300 ข้อความ นับตามจำนวนคนรับ · 10 คน x 30 วัน = 300
BROADCAST_DAILY_LIMIT = _int("BROADCAST_DAILY_LIMIT", 10)


DEV_ROUTES_ENABLED = _flag("DEV_ROUTES_ENABLED")

QUOTA_LIMIT_BY = os.getenv("QUOTA_LIMIT_BY", "both").strip().lower()
QUOTA_ENABLED = QUOTA_LIMIT_BY != "off"
QUOTA_WINDOW_HOURS = _int("QUOTA_WINDOW_HOURS", 6)

QUOTA_DAY_CALLS = _int("QUOTA_DAY_CALLS", 2500)
QUOTA_WINDOW_CALLS = _int("QUOTA_WINDOW_CALLS", 900)
QUOTA_DAY_TOKENS = _int("QUOTA_DAY_TOKENS", 22_000_000)
QUOTA_WINDOW_TOKENS = _int("QUOTA_WINDOW_TOKENS", 8_000_000)

QUOTA_YELLOW_CALLS = _int("QUOTA_YELLOW_CALLS", 150)
QUOTA_YELLOW_TOKENS = _int("QUOTA_YELLOW_TOKENS", 1_300_000)

QUOTA_USER_TURNS = _int("QUOTA_USER_TURNS", 60)
QUOTA_USER_YELLOW_TURNS = _int("QUOTA_USER_YELLOW_TURNS", 45)

QUOTA_RUSH_TURNS = _int("QUOTA_RUSH_TURNS", 15)
QUOTA_RUSH_SECONDS = _int("QUOTA_RUSH_SECONDS", 300)

QUOTA_DRAFT_TURNS = _int("QUOTA_DRAFT_TURNS", 40)
