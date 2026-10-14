"""เพดาน token ต่อผู้แจ้งต่อวัน (#239) — กันคนเดียวใช้งบ AI ของทุกคนจนหมด"""

from linebot.v3.messaging import TextMessage

from app.clients import database
from app.models.user import User

# ถ้อยคำตายตัว — TC7 ข้อยกเว้น 1 (ข้อความสำรองตอนโควตาหมด)
LIMIT_REACHED_TEXT = "วันนี้คุยกันครบโควตาแล้วค่ะ เรื่องที่เล่ามาเก็บไว้ครบแล้วนะคะ พรุ่งนี้มาคุยกันต่อได้ค่ะ"


async def is_over_daily_limit(user: User) -> bool:
    """token ที่ใช้วันนี้ถึงเพดานของ ai_configs แถวที่เลือกแล้ว · รู้ยอดหลังเรียก AI เสร็จ รอบสุดท้ายจึงเกินได้หนึ่งรอบ"""
    config = await database.select_active_ai_config()
    return await database.sum_user_tokens_today(user.user_id) >= config.user_daily_token_limit


def limit_reached_message() -> TextMessage:
    return TextMessage(text=LIMIT_REACHED_TEXT)
