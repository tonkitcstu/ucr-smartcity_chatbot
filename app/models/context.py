from typing import Literal

from pydantic import BaseModel


class ContextMessage(BaseModel):
    """หนึ่งรายการในบทสนทนาที่ส่งให้ AI · image → content = path ไฟล์รูป"""
    role: Literal["system", "user", "assistant"]
    type: Literal["text", "image"]
    content: str
