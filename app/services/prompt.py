"""ประกอบบทสนทนาที่ส่งให้ AI"""

from app.clients import database
from app.models.ai import AiConfig
from app.models.attachment import Attachment
from app.models.context import ContextMessage
from app.models.message import Message


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


async def for_chat(
    config: AiConfig, history: list[ContextMessage], new_context: list[ContextMessage]
) -> list[ContextMessage]:
    """[system: prompt ของตัวคุย] + ประวัติ + รอบนี้"""
    prompt = await database.select_prompt(config.chat_prompt_id)
    return [ContextMessage(role="system", type="text", content=prompt.prompt), *history, *new_context]
