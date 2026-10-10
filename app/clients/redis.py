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
    """BLPOP — คิวว่างก็รอจนมีใบ"""
    _, raw = await client.blpop(["jobs"], timeout=0)
    return Job.model_validate_json(raw)


async def get_last_message_at(session_id: UUID) -> float:
    return float(await client.get(_key(session_id, "last_message_at")))


async def set_processing(session_id: UUID) -> None:
    await client.set(_key(session_id, "state"), "PROCESSING")


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


async def clear_state(session_id: UUID) -> None:
    """ลบ key = IDLE"""
    await client.delete(_key(session_id, "state"))


async def set_closing_if_idle(session_id: UUID) -> bool:
    """ไม่มี key = IDLE · คำสั่งเดียว: ไม่มี key → ตั้ง CLOSING คืน True · มีแล้ว → คืน False"""
    return bool(await client.set(_key(session_id, "state"), "CLOSING", nx=True))


async def clear_session(session_id: UUID) -> None:
    """ลบทุก key ของใบ"""
    await client.delete(*[_key(session_id, name) for name in ("buffer", "last_message_at", "state", "history")])


async def buffer_length(session_id: UUID) -> int:
    return await client.llen(_key(session_id, "buffer"))
