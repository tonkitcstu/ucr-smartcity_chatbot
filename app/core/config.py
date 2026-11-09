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

# ทักผู้แจ้งไปก่อนทุกวัน · ฝนจะตกบอกเรื่องฝน วันอื่นทักถามไถ่ · ค่าตั้งต้นปิด เพราะเปิดแล้วส่งข้อความหาผู้แจ้งจริง
BROADCAST_ENABLED = _flag("BROADCAST_ENABLED")
# ที่อยู่ไฟล์พยากรณ์รายวันที่ Lambda อัปโหลด · {date} แทนด้วย YYYY-MM-DD · ว่าง = ใช้ mock_forecast.json (ไม่มีฝน)
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
# คนที่ได้ข้อความทักไปแล้ว ไม่ทักอีกจนครบกี่วัน · 7 = ได้วันจันทร์ ทักอีกได้วันจันทร์หน้า · 1 = ทุกวัน
# ต่ำสุด 1 เพราะ 0 ทำให้ทักต่อหลังแอปดับเลือกคนที่ได้ไปแล้ววันนี้ซ้ำ
BROADCAST_GAP_DAYS = max(1, _int("BROADCAST_GAP_DAYS", 7))

