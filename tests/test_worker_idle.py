"""worker รอคิวว่างได้ไม่จำกัดเวลา — redis-py 8 ตัดการรออ่านที่ 5 วิ ถ้าไม่ได้ตั้งเป็นอย่างอื่น"""

import asyncio
from uuid import uuid4


async def test_worker_keeps_waiting_while_queue_is_empty(client, redis):
    """คิวว่างเกิน 5 วิ → ยังรออยู่ · งานที่มาทีหลังยังถูกหยิบ"""
    from app.models.job import Job
    from app.services import job

    session_id = uuid4()
    waiting = asyncio.create_task(job.next())
    try:
        await asyncio.sleep(6)
        assert not waiting.done(), f"หยุดรอไปแล้ว: {waiting.exception()!r}"

        await redis.rpush("jobs", Job(kind="chat", session_id=session_id).model_dump_json())

        assert await asyncio.wait_for(waiting, 2) == Job(kind="chat", session_id=session_id)
    finally:
        waiting.cancel()
