from uuid import UUID

from pydantic import BaseModel


class AiConfig(BaseModel):
    """ai_configs แถวที่ใช้ (is_active) — ชุด model + prompt ของตัวคุยและตัววิเคราะห์
    + เพดาน token ต่อผู้แจ้งต่อวัน + เพดานข้อความใน buffer ต่อใบ"""
    ai_config_id: UUID
    chat_model_id: UUID
    chat_prompt_id: UUID
    analyzer_model_id: UUID
    analyzer_prompt_id: UUID
    user_daily_token_limit: int
    session_buffer_limit: int


class AiModel(BaseModel):
    """models"""
    model_id: UUID
    provider: str
    name: str


class Prompt(BaseModel):
    """prompts"""
    prompt_id: UUID
    prompt: str


class AiReply(BaseModel):
    """คำตอบจาก AI หนึ่งครั้ง"""
    text: str
    input_tokens: int | None
    output_tokens: int | None
