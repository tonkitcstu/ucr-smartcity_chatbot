"""สมองเบื้องหลัง: หยิบใบสั่งงาน แยกเป็น asyncio task ต่อใบ"""

import asyncio
import time
from uuid import UUID

from linebot.v3.messaging import TextMessage

from app.clients import line
from app.core.config import SILENCE_SECONDS
from app.models.job import Job
from app.services import attachment, communicator, job, prompt, session, user

# อ้างถึง task ที่ยังทำอยู่ ไม่ให้โดนเก็บกวาดกลางทาง
running: set[asyncio.Task] = set()


async def run() -> None:
    """วนไม่จบ · คน A รอเงียบ คน B ไม่ต้องรอด้วย"""
    while True:
        next_job = await job.next()
        task = asyncio.create_task(run_chat(next_job))
        running.add(task)
        task.add_done_callback(running.discard)


async def run_chat(job: Job) -> None:
    """งานคุยหนึ่งใบ: รอเงียบ → PROCESSING → loading → เก็บรูป → AI → reply ด้วย token ล่าสุด → IDLE"""
    session_id = job.session_id
    await wait_for_silence(session_id)
    await session.start_processing(session_id)
    await line.show_loading(await user.line_id_for(session_id))

    buffer = await session.read_buffer(session_id)
    attachments = [await attachment.save(message) for message in buffer if message.type == "image"]

    config = await prompt.latest_config()
    this_turn = prompt.turn(buffer, attachments)
    messages = await prompt.for_chat(config, await session.read_history(session_id), this_turn)
    answer = await communicator.chat(session_id, config, messages)

    await line.reply(buffer[-1].reply_token, [TextMessage(text=answer)])
    await session.finish(session_id, buffer, this_turn, answer)


async def wait_for_silence(session_id: UUID) -> None:
    """ยังเงียบไม่ครบ SILENCE_SECONDS → หลับเท่าที่ขาดแล้วอ่านใหม่"""
    while True:
        left = SILENCE_SECONDS - (time.time() - await session.last_message_at(session_id))
        if left <= 0:
            return
        await asyncio.sleep(left)
