# การทักผู้แจ้งไปก่อน: จดพยากรณ์ของวัน, ดูว่าถึงขั้นไหนแล้ว, หาคนที่จะทัก, เปิดใบให้คนที่ทัก
# หนึ่งวันมีแถวเดียวใน broadcasts · สถานะของแถวคือตัวบอกว่าวันนี้ทำถึงไหนแล้ว

from datetime import date

from app.clients import database, line, weather
from app.core.config import BROADCAST_DAILY_LIMIT, BROADCAST_SEND_AT, BROADCAST_SEND_UNTIL
from app.models.answer import ChatAnswer
from app.models.broadcast import Broadcast
from app.models.session import Session
from app.models.user import User


# แถวของวันนั้น · None = ยังไม่ได้อ่านพยากรณ์ของวันนั้น
async def find_for(day: date) -> Broadcast | None:
    return await database.select_broadcast(day)


# เหตุที่ทัก ส่งให้ตัวคุยใช้แต่งข้อความ
RAIN_REASON = "พยากรณ์อากาศบอกว่าวันนี้อาจมีฝนแถวบ้าน"


# อ่านพยากรณ์ของวันนั้นแล้วจดลงฐาน · ฝนจะตกในช่วงที่ทักได้ → รอทัก (scheduled) · ไม่ตก → ไม่ทัก (skipped)
async def check_forecast(day: date) -> Broadcast:
    forecast = await weather.fetch_daily(day)
    rain = weather.will_rain(forecast, BROADCAST_SEND_AT, BROADCAST_SEND_UNTIL)
    return await database.insert_broadcast(day, RAIN_REASON if rain else None)


# จดข้อความทักที่ตัวคุยแต่งแล้ว · คนถัดไปและการทักต่อหลังแอปดับใช้ข้อความนี้
async def save_greeting(broadcast: Broadcast, greeting: ChatAnswer) -> None:
    await database.save_broadcast_greeting(broadcast.broadcast_id, greeting)


async def mark_sent(broadcast: Broadcast) -> None:
    await database.mark_broadcast_sent(broadcast.broadcast_id)


async def mark_expired(broadcast: Broadcast) -> None:
    await database.mark_broadcast_expired(broadcast.broadcast_id)


# คนที่จะทักรอบนี้ สุ่มจากทุกคนที่ยอมรับ PDPA แล้ว · ยังไม่รู้ว่าใครอยู่ชุมชนไหน
# จำนวน = BROADCAST_DAILY_LIMIT ลบคนที่ได้ไปแล้ววันนี้ (แอปดับกลางทาง) · ไม่เกินข้อความที่เหลือของเดือนใน LINE
async def recipients(broadcast: Broadcast) -> list[User]:
    count = BROADCAST_DAILY_LIMIT - await database.count_broadcast_sessions(broadcast.broadcast_id)
    left = await line.monthly_messages_left()
    if left is not None:
        count = min(count, left)
    if count <= 0:
        return []
    return await database.select_broadcast_recipients(broadcast.broadcast_id, count)


# เปิดใบที่ติดป้ายว่าบอททักไปก่อน · None = ไม่ทักคนนี้
#   คนที่มีใบเปิดอยู่ (กำลังคุยกันอยู่) ไม่ขัดจังหวะ · คนที่ได้ใบของการทักครั้งนี้ไปแล้วไม่ทักซ้ำ
async def open_session_for(recipient: User, broadcast: Broadcast) -> Session | None:
    return await database.open_broadcast_session(recipient.user_id, broadcast.broadcast_id)
