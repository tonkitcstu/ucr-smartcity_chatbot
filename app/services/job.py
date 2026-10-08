"""ใบสั่งงานให้ worker"""

from app.clients import redis
from app.models.job import Job
from app.models.session import Session


async def enqueue_chat(session: Session) -> None:
    await redis.push_job(Job(kind="chat", session_id=session.session_id))
