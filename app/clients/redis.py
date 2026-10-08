"""Redis — ของชั่วคราว: buffer, เวลาข้อความล่าสุด, state, คิวงาน"""

from uuid import UUID

from redis.asyncio import Redis

from app.core.config import REDIS_URL
from app.models.job import Job
from app.models.message import Message

client: Redis | None = None


async def connect() -> None:
    global client
    client = Redis.from_url(REDIS_URL, decode_responses=True)


async def close() -> None:
    await client.aclose()


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
