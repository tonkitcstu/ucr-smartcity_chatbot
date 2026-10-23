# การทักผู้แจ้งไปก่อน: จดพยากรณ์ของวัน, ดูว่าถึงขั้นไหนแล้ว, หาคนที่จะทัก, เปิดใบให้คนที่ทัก
# หนึ่งวันมีแถวเดียวใน broadcasts · สถานะของแถวคือตัวบอกว่าวันนี้ทำถึงไหนแล้ว

from datetime import date

from app.clients import database, weather
from app.models.broadcast import Broadcast
from app.models.session import Session
from app.models.user import User


# แถวของวันนั้น · None = ยังไม่ได้อ่านพยากรณ์ของวันนั้น
async def find_for(day: date) -> Broadcast | None:
    return await database.select_broadcast(day)


# อ่านพยากรณ์ของวันนั้นแล้วจดลงฐาน · ฝนจะตก → รอทัก (scheduled) · ไม่ตก → ไม่ทัก (skipped)
async def check_forecast(day: date) -> Broadcast:
    forecast = await weather.fetch_daily(day)
    hours = weather.rain_hours(forecast)
    reason = f"พยากรณ์อากาศบอกว่าวันนี้อาจมีฝนช่วง {hours[0]} ถึง {hours[-1]} น." if hours else None
    return await database.insert_broadcast(day, forecast, reason)


async def mark_sent(broadcast: Broadcast) -> None:
    await database.mark_broadcast_sent(broadcast.broadcast_id)


async def mark_expired(broadcast: Broadcast) -> None:
    await database.mark_broadcast_expired(broadcast.broadcast_id)


# ทุกคนที่ยอมรับ PDPA แล้ว · ยังไม่รู้ว่าใครอยู่ชุมชนไหน จึงทักทุกคน
async def recipients() -> list[User]:
    return await database.select_all_users()


# เปิดใบที่ติดป้ายว่าบอททักไปก่อน · None = ไม่ทักคนนี้
#   คนที่มีใบเปิดอยู่ (กำลังคุยกันอยู่) ไม่ขัดจังหวะ · คนที่ได้ใบของการทักครั้งนี้ไปแล้วไม่ทักซ้ำ
async def open_session_for(recipient: User, broadcast: Broadcast) -> Session | None:
    return await database.open_broadcast_session(recipient.user_id, broadcast.broadcast_id)
