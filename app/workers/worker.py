"""สมองเบื้องหลัง: หยิบใบสั่งงาน แยกเป็น asyncio task ต่อใบ"""

import asyncio
import logging
import time
from uuid import UUID

from linebot.v3.messaging import TextMessage

from app.clients import line
from app.core.config import SILENCE_SECONDS
from app.models.job import Job
from app.models.message import Message
from app.services import analyser, attachment, communicator, job, prompt, report, session, state, user

# อ้างถึง task ที่ยังทำอยู่ ไม่ให้โดนเก็บกวาดกลางทาง
running: set[asyncio.Task] = set()

logger = logging.getLogger(__name__)

# รอ AI ได้ไม่เกินนี้ · reply token ของ LINE ใช้ได้ 1 นาที (TC9) จึงต้องเหลือเวลาตอบข้อความสำรอง (#213)
AI_TIMEOUT_SECONDS = 50
# ถ้อยคำตายตัว — TC7 ข้อยกเว้น 1 (ข้อความสำรองตอน AI ล่ม)
FALLBACK_TEXT = "ตอนนี้ระบบขัดข้องค่ะ เรื่องที่เล่ามายังอยู่ครบ ลองส่งมาอีกครั้งในอีกสักครู่นะคะ"


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
    """งานคุยหนึ่งใบ: รอเงียบ → PROCESSING → loading → เก็บรูป → AI → reply ด้วย token ล่าสุด → IDLE → ข้อความค้าง = งานใหม่
    reply ครั้งเดียวทุกข้อความที่ AI แยกมา · ปุ่มที่ AI เลือกอยู่ที่ข้อความสุดท้าย (LINE แสดงปุ่มของข้อความสุดท้ายเท่านั้น)
    ใบถูกพักระหว่างรอเงียบ (#239) → จบงาน ไม่เรียก AI ไม่ reply (controller ตอบข้อความแข็งไปแล้ว)
    ขั้นไหนพังหรือ AI ช้าเกิน AI_TIMEOUT_SECONDS (#213) → ข้อความสำรอง · buffer อยู่ครบ รอบหน้า AI เห็น · IDLE
    ไม่ออกงานใหม่เอง — AI ยังล่มอยู่จะวนพังไม่จบ · ข้อความถัดไปของผู้แจ้งได้งานคุยตามปกติ"""
    session_id = job.session_id
    await wait_for_silence(session_id)
    if not await state.start_processing(session_id):
        return
    buffer = await session.read_buffer(session_id)
    try:
        await answer_buffer(session_id, buffer)
    except Exception:
        logger.exception("งานคุยของใบ %s พัง", session_id)
        await reply_fallback(session_id, buffer)
        await state.finish_processing(session_id)
        return
    await state.finish_processing(session_id)
    await chat_again_if_waiting(session_id)


async def answer_buffer(session_id: UUID, buffer: list[Message]) -> None:
    """loading → เก็บรูป → AI → reply ด้วย token ล่าสุด → บันทึกคำตอบ ตัดข้อความที่ตอบแล้วออกจาก buffer"""
    await line.show_loading(await user.line_id_for(session_id))
    attachments = [await attachment.save(message) for message in buffer if message.type == "image"]

    config = await prompt.active_config()
    new_context = prompt.buffer_to_context(buffer, attachments)
    messages = await prompt.build_chat_context(config, await session.read_history(session_id), new_context)
    async with asyncio.timeout(AI_TIMEOUT_SECONDS):
        answer = await communicator.chat(session_id, config, messages)

    replies = [TextMessage(text=text) for text in answer.texts[:-1]]
    replies.append(TextMessage(text=answer.texts[-1], quick_reply=line.build_quick_reply(answer.buttons)))
    await line.reply(buffer[-1].reply_token, replies)
    await session.finish(session_id, buffer, new_context, answer.texts)


async def reply_fallback(session_id: UUID, buffer: list[Message]) -> None:
    """ใบถูกพักระหว่าง AI ตอบ → ไม่ตอบ (controller ตอบข้อความแข็งไปแล้ว) · ตัดข้อความรอบนี้ออกจาก buffer
    ไม่ถูกพัก → ข้อความสำรองด้วย token ล่าสุด · reply ไม่ผ่าน (token หมดอายุ) → จดไว้ ไม่มีทางอื่นตอบ"""
    if await state.is_suspended(session_id):
        await session.drop_answered(session_id, buffer)
        return
    try:
        await line.reply(buffer[-1].reply_token, [TextMessage(text=FALLBACK_TEXT)])
    except Exception:
        logger.exception("ตอบข้อความสำรองของใบ %s ไม่ผ่าน", session_id)


async def chat_again_if_waiting(session_id: UUID) -> None:
    """ข้อความที่เข้ามาระหว่าง AI ตอบยังค้างใน buffer → งานคุยรอบใหม่ (#240)
    คืน IDLE ก่อนแล้วค่อยดู buffer · ข้อความที่เข้ามาพร้อมกัน controller กับ worker แย่ง IDLE → BUFFERING ได้คนเดียว
    จึงได้ใบสั่งงานใบเดียว · ใบถูกพักระหว่าง AI ตอบ → ยังเป็น SUSPENDED แย่งไม่ได้ ไม่มีงานใหม่"""
    if await session.has_buffer(session_id) and await state.start_buffering(session_id):
        await job.enqueue_chat(session_id)


async def run_analyse(job: Job) -> None:
    """งานวิเคราะห์หนึ่งใบ: บทสนทนาทั้งใบที่ไม่ใช่ skipped → AI → รายงาน 0..n → ใบ analysed
    ใบที่มีแต่ข้อความ skipped (#239) → ใบ analysed ไม่เรียก AI ไม่มีรายงาน"""
    session_id = job.session_id
    transcript = await session.read_transcript_for_analysis(session_id)
    if not transcript:
        await session.mark_analysed(session_id)
        return
    config = await prompt.active_config()
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
