from dotenv import load_dotenv
import os
from pathlib import Path



# app/core/config.py -> app/core -> app -> project root
BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")

API_KEY = os.getenv("API_KEY")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DATABASE_URL = os.getenv("DATABASE_URL")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

# **ต้องเป็น base ของช่องทางที่พูดภาษา OpenAI ไม่ใช่ URL ของ endpoint ตัวเดียว**
# ของ Gemini คือ .../v1beta/openai/ ไม่ใช่ .../v1beta/models/<model>:generateContent
# (อันหลังเป็น REST ดั้งเดิมของ Google คนละภาษากับที่ไลบรารีนี้พูด)
# ตั้ง default ไว้ให้ เพราะเป็นค่าที่ถูกอยู่แล้ว ไม่ต้องให้ทุกคนไปจำเอง
API_ENDPOINT = os.getenv(
    "API_ENDPOINT", "https://generativelanguage.googleapis.com/v1beta/openai/"
)

# โมเดลคิดหนักแค่ไหนก่อนตอบ: low | medium | high
#
# **ค่าตั้งต้นยังเป็น high ตั้งใจ** — วัดแล้วว่า low ประหยัดกว่า 18% และเร็วกว่า 2.9 เท่า
# โดยยังไม่เห็นว่าโง่ลง แต่วัดมาแค่บทสนทนาละหนึ่งรอบ ซึ่งบางเกินกว่าจะเปลี่ยนค่า
# ตั้งต้นของตัวที่ทำหน้าที่กันการปั้นเรื่อง ตัวเลขเต็มอยู่ใน clients/llm.py
#
# มาเป็น env เพื่อให้ลองของจริงได้โดยไม่ต้องแก้โค้ด — ลอง low สักพัก อ่านใบที่ได้
# แล้วค่อยตัดสินว่าจะย้ายค่าตั้งต้นไหม
REASONING_EFFORT = os.getenv("REASONING_EFFORT", "high").strip().lower()

# **ยิงข้อความหาชาวบ้านจริงหรือยัง** — ปิดไว้โดยปริยาย ตั้งใจ
#
# การขึ้นโค้ดกับการเริ่มทักคนจริงเป็นคนละการตัดสินใจกัน ตัวนี้ทำให้หยุดยิงได้
# ด้วยการแก้ .env แล้วรีสตาร์ท ไม่ต้องถอยโค้ด
BROADCAST_ENABLED = os.getenv("BROADCAST_ENABLED", "").lower() in ("1", "true", "yes")

