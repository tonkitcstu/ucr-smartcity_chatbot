"""เพดานของผู้แจ้ง (#239) — ① token ต่อผู้แจ้งต่อวัน กันคนเดียวใช้งบ AI ของทุกคนจนหมด
② ข้อความใน buffer ต่อใบ กันคนส่งข้อความรัวจนบอทต้องส่งก้อนใหญ่ให้ AI
③ token ทั้งระบบต่อวัน กันหลายคนรวมกันใช้งบ AI ของแล็บเกิน · ① และ ③ นับเฉพาะตัวคุย"""

from linebot.v3.messaging import TextMessage

from app.clients import database, redis
from app.models.session import Session
from app.models.user import User

# ถ้อยคำตายตัว — TC7 ข้อยกเว้น 1 (ข้อความสำรองตอนโควตาหมด)
LIMIT_REACHED_TEXT = "วันนี้คุยกันครบโควตาแล้วค่ะ เรื่องที่เล่ามาเก็บไว้ครบแล้วนะคะ พรุ่งนี้มาคุยกันต่อได้ค่ะ"
SUSPENDED_TEXT = "ตอนนี้ได้รับข้อความเยอะเกินไปค่ะ ขอพักการคุยไว้ก่อนนะคะ พรุ่งนี้มาคุยกันต่อได้ค่ะ"


async def is_over_daily_limit(user: User) -> bool:
    """token ที่ใช้วันนี้ถึงเพดานของ ai_configs แถวที่เลือกแล้ว · รู้ยอดหลังเรียก AI เสร็จ รอบสุดท้ายจึงเกินได้หนึ่งรอบ"""
    config = await database.select_active_ai_config()
    return await database.sum_user_tokens_today(user.user_id) >= config.user_daily_token_limit


async def is_over_system_daily_limit() -> bool:
    """token ที่ผู้แจ้งทุกคนใช้วันนี้ถึงเพดานของ ai_configs แถวที่เลือกแล้ว · รอบคุยที่กำลังเกิดตอนถึงเพดานเกินได้หนึ่งรอบ"""
    config = await database.select_active_ai_config()
    return await database.sum_system_tokens_today() >= config.system_daily_token_limit


def limit_reached_message() -> TextMessage:
    return TextMessage(text=LIMIT_REACHED_TEXT)


async def is_buffer_full(session: Session) -> bool:
    """ข้อความที่บอทยังไม่ได้ตอบใน buffer ของใบครบเพดานของ ai_configs แถวที่เลือกแล้ว · รูปนับรูปละหนึ่งข้อความ"""
    config = await database.select_active_ai_config()
    return await redis.buffer_length(session.session_id) >= config.session_buffer_limit


def suspended_message() -> TextMessage:
    return TextMessage(text=SUSPENDED_TEXT)
