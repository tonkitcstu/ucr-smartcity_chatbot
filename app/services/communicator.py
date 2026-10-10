"""ตัวคุย: เรียก AI → บันทึก ai_calls → คืนคำตอบ (ไม่รู้จัก LINE)"""

from uuid import UUID

from app.clients import ai, database
from app.models.ai import AiConfig
from app.models.context import ContextMessage


async def chat(session_id: UUID, config: AiConfig, messages: list[ContextMessage]) -> str:
    model = await database.select_model(config.chat_model_id)
    reply = await ai.chat(model.name, messages)
    await database.insert_ai_call(session_id, config.ai_config_id, "communicator", messages, reply)
    return reply.text
