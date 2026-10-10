"""ประกอบบทสนทนาที่ส่งให้ AI"""

from app.clients import database
from app.core import default_config
from app.models.ai import AiConfig
from app.models.attachment import Attachment
from app.models.context import ContextMessage
from app.models.message import Message, TranscriptMessage


# ใบปิดเพราะเงียบจนหมดเวลา — บรรทัดสุดท้ายที่ตัววิเคราะห์เห็น
SESSION_EXPIRED = "//leave chat because session expired"


async def ensure_default_config() -> None:
    """PSQL เป็นตัวจริง · หา ai_configs ไม่เจอ (ฐานใหม่) → ใส่ค่าจาก default_config"""
    if await database.has_ai_config():
        return
    await database.insert_ai_config(
        default_config.PROVIDER,
        default_config.CHAT_MODEL,
        default_config.CHAT_PROMPT,
        default_config.ANALYSER_MODEL,
        default_config.ANALYSER_PROMPT,
    )


async def latest_config() -> AiConfig:
    """ai_configs แถวล่าสุด"""
    return await database.select_latest_ai_config()


def buffer_to_context(buffer: list[Message], attachments: list[Attachment]) -> list[ContextMessage]:
    """buffer → ContextMessage role user · text → ข้อความ · image → path ไฟล์ของ attachment"""
    file_paths = {item.message_id: item.file_path for item in attachments}
    return [
        ContextMessage(role="user", type="image", content=file_paths[message.message_id])
        if message.type == "image"
        else ContextMessage(role="user", type="text", content=message.content)
        for message in buffer
    ]


async def build_chat_context(
    config: AiConfig, history: list[ContextMessage], new_context: list[ContextMessage]
) -> list[ContextMessage]:
    """[system: prompt ของตัวคุย] + ประวัติ + รอบนี้"""
    prompt = await database.select_prompt(config.chat_prompt_id)
    return [ContextMessage(role="system", type="text", content=prompt.prompt), *history, *new_context]


async def build_analyse_context(config: AiConfig, transcript: list[TranscriptMessage]) -> list[ContextMessage]:
    """[system: prompt ของตัววิเคราะห์] + บทสนทนาทั้งใบ + บรรทัดปิดท้ายฝั่ง user
    รูปมีป้าย [รูป n] นำหน้า · ตำแหน่งเป็นป้าย [ตำแหน่ง n] · n นับจาก 1 แยกชนิด ตามลำดับในบทสนทนา
    ปิดท้ายด้วย SESSION_EXPIRED — Gemini ไม่รับคำขอที่จบด้วย assistant (#202)"""
    prompt = await database.select_prompt(config.analyzer_prompt_id)
    context = [ContextMessage(role="system", type="text", content=prompt.prompt)]
    images = locations = 0
    for message in transcript:
        if message.type == "image":
            images += 1
            context.append(ContextMessage(role=message.role, type="text", content=f"[รูป {images}]"))
            context.append(ContextMessage(role=message.role, type="image", content=message.file_path))
        elif message.type == "location":
            locations += 1
            context.append(ContextMessage(role=message.role, type="text", content=f"[ตำแหน่ง {locations}]"))
        else:
            context.append(ContextMessage(role=message.role, type="text", content=message.content))
    context.append(ContextMessage(role="user", type="text", content=SESSION_EXPIRED))
    return context
