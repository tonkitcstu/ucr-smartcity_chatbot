"""ประกอบบทสนทนาที่ส่งให้ AI"""

from app.clients import database
from app.models.ai import AiConfig
from app.models.attachment import Attachment
from app.models.context import ContextMessage
from app.models.message import Message, TranscriptMessage


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
    """[system: prompt ของตัววิเคราะห์] + บทสนทนาทั้งใบ
    รูปมีป้าย [รูป n] นำหน้า · ตำแหน่งเป็นป้าย [ตำแหน่ง n] · n นับจาก 1 แยกชนิด ตามลำดับในบทสนทนา"""
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
    return context
