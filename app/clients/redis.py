"""Redis — ของชั่วคราว: buffer, เวลาข้อความล่าสุด, state, ประวัติที่คุยมา, คิวงาน"""

from uuid import UUID

from redis.asyncio import Redis

from app.core.config import REDIS_URL
from app.models.context import ContextMessage
from app.models.job import Job
from app.models.message import Message

client: Redis | None = None


async def connect() -> None:
    global client
    client = Redis.from_url(REDIS_URL, decode_responses=True)


async def close() -> None:
    await client.aclose()


async def ping() -> bool:
    """Redis ตอบ → True · ต่อไม่ได้ / error → False"""
    try:
        await client.ping()
        return True
    except Exception:
        return False


def _key(session_id: UUID, name: str) -> str:
    return f"session:{session_id}:{name}"


async def append_buffer(message: Message) -> None:
    await client.rpush(_key(message.session_id, "buffer"), message.model_dump_json())


async def set_last_message_at(session_id: UUID, at: float) -> None:
    await client.set(_key(session_id, "last_message_at"), at)


async def set_buffering_if_idle(session_id: UUID) -> bool:
    """ไม่มี key = IDLE · คำสั่งเดียว: ไม่มี key → ตั้ง คืน True · มีแล้ว → คืน False"""
    return bool(await client.set(_key(session_id, "state"), "BUFFERING", nx=True))


async def push_job(job: Job) -> None:
    await client.rpush("jobs", job.model_dump_json())


async def pop_job() -> Job:
    """BLPOP — คิวว่างก็รอจนมีใบ · ถามทีละ 1 วิ เพราะ redis-py ตัดการรออ่านที่ 5 วิ"""
    while True:
        item = await client.blpop(["jobs"], timeout=1)
        if item:
            return Job.model_validate_json(item[1])


async def get_last_message_at(session_id: UUID) -> float:
    return float(await client.get(_key(session_id, "last_message_at")))


# SET ... IFEQ และ DELEX ... IFEQ ส่งเป็นคำสั่งดิบ — redis-py ยังจัดสองตัวนี้เป็นของทดลอง (เตือนทุกครั้งที่เรียก)
async def set_processing_if_buffering(session_id: UUID) -> bool:
    """คำสั่งเดียว: state เป็น BUFFERING → ตั้ง PROCESSING คืน True · เป็นอย่างอื่น → คืน False (Redis 8.4 ขึ้นไป)"""
    return bool(await client.execute_command("SET", _key(session_id, "state"), "PROCESSING", "IFEQ", "BUFFERING"))


async def get_buffer(session_id: UUID) -> list[Message]:
    items = await client.lrange(_key(session_id, "buffer"), 0, -1)
    return [Message.model_validate_json(item) for item in items]


async def get_history(session_id: UUID) -> list[ContextMessage]:
    items = await client.lrange(_key(session_id, "history"), 0, -1)
    return [ContextMessage.model_validate_json(item) for item in items]


async def append_history(session_id: UUID, items: list[ContextMessage]) -> None:
    await client.rpush(_key(session_id, "history"), *[item.model_dump_json() for item in items])


async def clear_buffer(session_id: UUID) -> None:
    await client.delete(_key(session_id, "buffer"))


async def get_state(session_id: UUID) -> str | None:
    """None = ไม่มี key = IDLE"""
    return await client.get(_key(session_id, "state"))


async def clear_state_if_processing(session_id: UUID) -> None:
    """คำสั่งเดียว: state เป็น PROCESSING → ลบ key = IDLE · เป็นอย่างอื่น → ไม่ลบ (Redis 8.4 ขึ้นไป)"""
    await client.execute_command("DELEX", _key(session_id, "state"), "IFEQ", "PROCESSING")


async def clear_state_if_closing(session_id: UUID) -> None:
    """คำสั่งเดียว: state เป็น CLOSING → ลบ key = IDLE · เป็นอย่างอื่น → ไม่ลบ (Redis 8.4 ขึ้นไป)"""
    await client.execute_command("DELEX", _key(session_id, "state"), "IFEQ", "CLOSING")


async def set_suspended(session_id: UUID, seconds: int) -> None:
    """เขียนทับได้ทุก state · หมดอายุเองใน seconds วินาทีแล้วใบเป็น IDLE"""
    await client.set(_key(session_id, "state"), "SUSPENDED", ex=seconds)


async def set_closing_if_idle(session_id: UUID) -> bool:
    """ไม่มี key = IDLE · คำสั่งเดียว: ไม่มี key → ตั้ง CLOSING คืน True · มีแล้ว → คืน False"""
    return bool(await client.set(_key(session_id, "state"), "CLOSING", nx=True))


async def clear_session(session_id: UUID) -> None:
    """ลบทุก key ของใบ"""
    await client.delete(*[_key(session_id, name) for name in ("buffer", "last_message_at", "state", "history")])


async def buffer_length(session_id: UUID) -> int:
    return await client.llen(_key(session_id, "buffer"))
