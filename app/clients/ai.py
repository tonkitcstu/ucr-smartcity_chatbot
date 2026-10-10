"""ภาษาของ AI: OpenAI SDK — ContextMessage → รูปแบบ OpenAI"""

import base64
from pathlib import Path

from openai import AsyncOpenAI

from app.core.config import API_ENDPOINT, GEMINI_API_KEY
from app.models.ai import AiReply
from app.models.context import ContextMessage


async def chat(model: str, messages: list[ContextMessage]) -> AiReply:
    """เรียกแบบ stream แล้วรวมเป็นคำตอบเดียว + token"""
    async with AsyncOpenAI(base_url=API_ENDPOINT, api_key=GEMINI_API_KEY) as client:
        stream = await client.chat.completions.create(
            model=model,
            messages=[to_openai(message) for message in messages],
            stream=True,
            stream_options={"include_usage": True},
        )
        parts, usage = [], None
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                parts.append(chunk.choices[0].delta.content)
            if chunk.usage:
                usage = chunk.usage
    return AiReply(
        text="".join(parts),
        input_tokens=usage.prompt_tokens if usage else None,
        output_tokens=usage.completion_tokens if usage else None,
    )


def to_openai(message: ContextMessage) -> dict:
    """text → content = ข้อความ · image → อ่านไฟล์เป็น base64"""
    if message.type == "text":
        return {"role": message.role, "content": message.content}
    encoded = base64.b64encode(Path(message.content).read_bytes()).decode()
    return {
        "role": message.role,
        "content": [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}}],
    }
