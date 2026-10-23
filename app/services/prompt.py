"""ประกอบบทสนทนาที่ส่งให้ AI"""

from app.clients import database
from app.core import default_config
from app.models.ai import AiConfig
from app.models.attachment import Attachment
from app.models.context import ContextMessage
from app.models.message import Message, TranscriptMessage


# ใบปิดเพราะเงียบจนหมดเวลา — บรรทัดสุดท้ายที่ตัววิเคราะห์เห็น
SESSION_EXPIRED = "//leave chat because session expired"

# ป้ายแทนสิ่งที่ผู้แจ้งทำในไลน์ — prompt ของตัวคุยและตัววิเคราะห์บอกไว้ว่าบรรทัด [ระบบ: ...] ไม่ใช่คำที่ผู้แจ้งพิมพ์
PIN_NOTE = "[ระบบ: ผู้แจ้งปักหมุดตำแหน่งแล้ว]"


# บรรทัดแรกที่ตัววิเคราะห์เห็นเมื่อบทสนทนาเริ่มจากบอททักไปก่อน
# บอกให้รู้ว่าข้อความแรกเป็นของบอท และ Gemini อาจไม่รับคำขอที่ขึ้นต้นด้วย assistant (แบบเดียวกับ #202)
BOT_STARTED_NOTE = "[ระบบ: บทสนทนานี้เมืองทักผู้แจ้งไปก่อน]"


# บรรทัดที่บอกตัวคุยว่าต้องเป็นฝ่ายทักไปก่อน และทักเพราะอะไร · หัวข้อ "ทักไปก่อน" ใน prompt ของตัวคุยอธิบายวิธีทัก
# เก็บไว้ในประวัติของใบด้วย ผู้แจ้งตอบกลับมาแล้วตัวคุยยังเห็นว่าตัวเองทักไปเพราะอะไร
def broadcast_note(reason: str) -> ContextMessage:
    return ContextMessage(
        role="user", type="text", content=f"[ระบบ: เมืองทักผู้แจ้งไปก่อน ผู้แจ้งยังไม่ได้พิมพ์อะไร เหตุที่ทัก: {reason}]"
    )


def sticker_note(keywords: str | None) -> str:
    """keywords = คำที่ LINE ใช้บรรยายสติกเกอร์ · LINE ไม่ส่งมา → ป้ายเปล่า"""
    return f"[ระบบ: ผู้แจ้งส่งสติกเกอร์ คำบรรยาย: {keywords}]" if keywords else "[ระบบ: ผู้แจ้งส่งสติกเกอร์]"


async def ensure_default_config() -> None:
    """PSQL เป็นตัวจริง · ไม่มีแถวที่ถูกเลือก (ฐานใหม่ หรือมีแถวแต่ยังไม่ได้เลือก) → ใส่ค่าจาก default_config เป็นแถวที่ใช้"""
    if await database.has_active_ai_config():
        return
    await database.insert_active_ai_config(
        default_config.PROVIDER,
        default_config.CHAT_MODEL,
        default_config.CHAT_PROMPT,
        default_config.ANALYSER_MODEL,
        default_config.ANALYSER_PROMPT,
    )


async def active_config() -> AiConfig:
    """ai_configs แถวที่แอดมินเลือก (is_active) — อ่านใหม่ทุกงาน สลับแถวแล้วมีผลงานถัดไปทันที"""
    return await database.select_active_ai_config()


def buffer_to_context(buffer: list[Message], attachments: list[Attachment]) -> list[ContextMessage]:
    """buffer → ContextMessage role user · text → ข้อความ · image → path ไฟล์ของ attachment
    ตำแหน่ง → PIN_NOTE (ตัวคุยไม่เห็นพิกัด) · สติกเกอร์ → sticker_note"""
    file_paths = {item.message_id: item.file_path for item in attachments}
    context = []
    for message in buffer:
        if message.type == "image":
            context.append(ContextMessage(role="user", type="image", content=file_paths[message.message_id]))
        elif message.type == "location":
            context.append(ContextMessage(role="user", type="text", content=PIN_NOTE))
        elif message.type == "sticker":
            context.append(ContextMessage(role="user", type="text", content=sticker_note(message.content)))
        else:
            context.append(ContextMessage(role="user", type="text", content=message.content))
    return context


async def build_chat_context(
    config: AiConfig, history: list[ContextMessage], new_context: list[ContextMessage]
) -> list[ContextMessage]:
    """[system: prompt ของตัวคุย] + ประวัติ + รอบนี้"""
    prompt = await database.select_prompt(config.chat_prompt_id)
    return [ContextMessage(role="system", type="text", content=prompt.prompt), *history, *new_context]


async def build_analyse_context(config: AiConfig, transcript: list[TranscriptMessage]) -> list[ContextMessage]:
    """[system: prompt ของตัววิเคราะห์] + บทสนทนาทั้งใบ + บรรทัดปิดท้ายฝั่ง user
    รูปมีป้าย [รูป n] นำหน้า · ตำแหน่งเป็นป้าย [ตำแหน่ง n] · n นับจาก 1 แยกชนิด ตามลำดับในบทสนทนา
    สติกเกอร์เป็น sticker_note บรรทัดเดียวกับที่ตัวคุยเห็น
    ปิดท้ายด้วย SESSION_EXPIRED — Gemini ไม่รับคำขอที่จบด้วย assistant (#202)"""
    prompt = await database.select_prompt(config.analyzer_prompt_id)
    context = [ContextMessage(role="system", type="text", content=prompt.prompt)]
    # บอททักไปก่อน → ข้อความแรกเป็นของบอท ขึ้นต้นด้วยบรรทัดของระบบก่อน
    if transcript and transcript[0].role == "assistant":
        context.append(ContextMessage(role="user", type="text", content=BOT_STARTED_NOTE))
    images = locations = 0
    for message in transcript:
        if message.type == "image":
            images += 1
            context.append(ContextMessage(role=message.role, type="text", content=f"[รูป {images}]"))
            context.append(ContextMessage(role=message.role, type="image", content=message.file_path))
        elif message.type == "location":
            locations += 1
            context.append(ContextMessage(role=message.role, type="text", content=f"[ตำแหน่ง {locations}]"))
        elif message.type == "sticker":
            context.append(ContextMessage(role=message.role, type="text", content=sticker_note(message.content)))
        else:
            context.append(ContextMessage(role=message.role, type="text", content=message.content))
    context.append(ContextMessage(role="user", type="text", content=SESSION_EXPIRED))
    return context
