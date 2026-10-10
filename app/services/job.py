"""ใบสั่งงานให้ worker: ใส่งาน, หยิบงาน"""

from app.clients import redis
from app.models.job import Job
from app.models.session import Session


async def enqueue_chat(session: Session) -> None:
    await redis.push_job(Job(kind="chat", session_id=session.session_id))


async def enqueue_analyse(session: Session) -> None:
    await redis.push_job(Job(kind="analyse", session_id=session.session_id))


async def next() -> Job:
    """หยิบใบสั่งงานใบแรก · คิวว่างก็รอ"""
    return await redis.pop_job()
