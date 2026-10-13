"""สมองเบื้องหลัง: หยิบใบสั่งงาน แยกเป็น asyncio task ต่อใบ"""

import asyncio
import time
from uuid import UUID

from linebot.v3.messaging import TextMessage

from app.clients import line
from app.core.config import SILENCE_SECONDS
from app.models.job import Job
from app.services import analyser, attachment, communicator, job, prompt, report, session, user

# อ้างถึง task ที่ยังทำอยู่ ไม่ให้โดนเก็บกวาดกลางทาง
running: set[asyncio.Task] = set()


async def run() -> None:
    """วนไม่จบ · คน A รอเงียบ คน B ไม่ต้องรอด้วย"""
    while True:
        next_job = await job.next()
        task = asyncio.create_task(handle(next_job))
        running.add(task)
        task.add_done_callback(running.discard)


async def handle(job: Job) -> None:
    """แยกงานตาม kind · chat → run_chat · analyse → run_analyse"""
    if job.kind == "chat":
        await run_chat(job)
    elif job.kind == "analyse":
        await run_analyse(job)


async def run_chat(job: Job) -> None:
    """งานคุยหนึ่งใบ: รอเงียบ → PROCESSING → loading → เก็บรูป → AI → reply ด้วย token ล่าสุด → IDLE
    reply ครั้งเดียวทุกข้อความที่ AI แยกมา · ปุ่มที่ AI เลือกอยู่ที่ข้อความสุดท้าย (LINE แสดงปุ่มของข้อความสุดท้ายเท่านั้น)"""
    session_id = job.session_id
    await wait_for_silence(session_id)
    await session.start_processing(session_id)
    await line.show_loading(await user.line_id_for(session_id))

    buffer = await session.read_buffer(session_id)
    attachments = [await attachment.save(message) for message in buffer if message.type == "image"]

    config = await prompt.latest_config()
    new_context = prompt.buffer_to_context(buffer, attachments)
    messages = await prompt.build_chat_context(config, await session.read_history(session_id), new_context)
    answer = await communicator.chat(session_id, config, messages)

    replies = [TextMessage(text=text) for text in answer.texts[:-1]]
    replies.append(TextMessage(text=answer.texts[-1], quick_reply=line.build_quick_reply(answer.buttons)))
    await line.reply(buffer[-1].reply_token, replies)
    await session.finish(session_id, buffer, new_context, answer.texts)


async def run_analyse(job: Job) -> None:
    """งานวิเคราะห์หนึ่งใบ: บทสนทนาทั้งใบ → AI → รายงาน 0..n → ใบ analysed"""
    session_id = job.session_id
    config = await prompt.latest_config()
    transcript = await session.read_transcript(session_id)
    messages = await prompt.build_analyse_context(config, transcript)
    drafts = await analyser.analyse(session_id, config, messages)
    await report.save(session_id, config, drafts, transcript)
    await session.mark_analysed(session_id)


async def wait_for_silence(session_id: UUID) -> None:
    """ยังเงียบไม่ครบ SILENCE_SECONDS → หลับเท่าที่ขาดแล้วอ่านใหม่"""
    while True:
        left = SILENCE_SECONDS - (time.time() - await session.last_message_at(session_id))
        if left <= 0:
            return
        await asyncio.sleep(left)
