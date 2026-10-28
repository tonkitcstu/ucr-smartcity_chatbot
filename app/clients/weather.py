# ภาษาของพยากรณ์อากาศ
# ของจริงคือไฟล์ JSON รายวันที่ Lambda ของทีม data อัปโหลดทุกตี 1 เวลาไทย (กรมอุตุนิยมวิทยา · ล่มแล้วใช้ Open-Meteo แทน)
# ไฟล์เก็บเฉพาะชั่วโมงที่ฝนตกหรือร้อนเกิน 35 องศา · ชุมชนที่ดึงไม่ได้มีแค่ error ไม่มี forecasts
# FORECAST_URL ว่าง → ตอบด้วย mock_forecast.json ที่หน้าตาเหมือนไฟล์จริง และบอกว่าวันนี้ฝนตกช่วง 14:00–15:00
#   อยากลองวันที่ฝนไม่ตก: แก้ "มีฝน" ในไฟล์เป็นคำอื่น และแก้ rainfall เป็น 0

import json
from datetime import date, datetime, time
from pathlib import Path

import httpx

from app.core.config import FORECAST_URL

MOCK_FILE = Path(__file__).parent / "mock_forecast.json"
FETCH_TIMEOUT_SECONDS = 10

# คำที่อยู่ใน condition_label แล้วแปลว่ามีฝน · ไฟล์จริงใช้ "มีฝน" "ฝนหนัก" "ฝนฟ้าคะนอง"
RAIN_WORD = "ฝน"


# พยากรณ์ของวันนั้นทั้งก้อน
# {"date": "YYYY-MM-DD", "WeatherForecasts": [{"name": ชุมชน, "location": {...}, "forecasts": [รายชั่วโมง]}]}
# ไฟล์ของวันนั้นยังไม่ขึ้น (S3 ตอบ 403) → httpx.HTTPStatusError · ตัวทักลองใหม่รอบหน้า
async def fetch_daily(day: date) -> dict:
    if not FORECAST_URL:
        return mock_daily(day)
    async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_SECONDS) as client:
        response = await client.get(FORECAST_URL.format(date=day.isoformat()))
    response.raise_for_status()
    return response.json()


def mock_daily(day: date) -> dict:
    forecast = json.loads(MOCK_FILE.read_text(encoding="utf-8"))
    # ของปลอมใช้ได้ทุกวัน จึงเปลี่ยนวันที่ของไฟล์เป็นวันที่ขอ
    forecast["date"] = day.isoformat()
    return forecast


# ชุมชนไหนก็ได้มีฝนสักชั่วโมงตั้งแต่ start ถึงก่อน until · ชุมชนที่ไม่มี forecasts (ดึงไม่ได้) ข้าม
def will_rain(forecast: dict, start: time, until: time) -> bool:
    return any(
        start <= datetime.fromisoformat(hour["time"]).time() < until and is_rain(hour)
        for community in forecast["WeatherForecasts"]
        for hour in community.get("forecasts", [])
    )


def is_rain(hour: dict) -> bool:
    return RAIN_WORD in (hour.get("condition_label") or "") or (hour.get("rainfall") or 0) > 0
