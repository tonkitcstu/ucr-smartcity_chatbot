import os
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

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
DASHBOARD_USER = os.getenv("DASHBOARD_USER", "ucr")
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD")
CORS_ORIGINS = [
    origin.strip().rstrip("/")
    for origin in (os.getenv("CORS_ORIGINS") or "").split(",")
    if origin.strip()
]

BROADCAST_ENABLED = _flag("BROADCAST_ENABLED")
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
