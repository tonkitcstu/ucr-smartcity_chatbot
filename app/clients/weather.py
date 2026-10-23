# ภาษาของพยากรณ์อากาศ
# ของจริงคือไฟล์ JSON รายวันที่ทีม data อัปโหลดทุกตี 1 เวลาไทย (ข้อมูลจากกรมอุตุนิยมวิทยา) · ยังไม่ได้ต่อ
# ตอนนี้ตอบด้วย mock_forecast.json ที่หน้าตาเหมือนไฟล์จริง และบอกว่าวันนี้ฝนตกช่วง 14:00–15:00
#   อยากลองวันที่ฝนไม่ตก: แก้ "มีฝน" ในไฟล์เป็นคำอื่น และแก้ rainfall เป็น 0

import json
from datetime import date, datetime
from pathlib import Path

MOCK_FILE = Path(__file__).parent / "mock_forecast.json"

# คำที่อยู่ใน condition_label แล้วแปลว่ามีฝน · ไฟล์จริงที่เคยเห็นใช้ "มีฝน"
RAIN_WORD = "ฝน"


# พยากรณ์ของวันนั้นทั้งก้อน
# {"date": "YYYY-MM-DD", "WeatherForecasts": [{"name": ชุมชน, "location": {...}, "forecasts": [รายชั่วโมง]}]}
async def fetch_daily(day: date) -> dict:
    forecast = json.loads(MOCK_FILE.read_text(encoding="utf-8"))
    # ของปลอมใช้ได้ทุกวัน จึงเปลี่ยนวันที่ของไฟล์เป็นวันที่ขอ
    forecast["date"] = day.isoformat()
    return forecast


# ชั่วโมงที่ชุมชนไหนก็ได้มีฝน เช่น ["14:00", "15:00"] เรียงจากเช้าไปค่ำ ไม่ซ้ำ · ไม่มีฝนเลย → ลิสต์ว่าง
def rain_hours(forecast: dict) -> list[str]:
    hours = set()
    for community in forecast["WeatherForecasts"]:
        for hour in community["forecasts"]:
            if RAIN_WORD in hour["condition_label"] or hour["rainfall"] > 0:
                hours.add(datetime.fromisoformat(hour["time"]).strftime("%H:%M"))
    return sorted(hours)
