from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class Job(BaseModel):
    """ใบสั่งงานให้ worker — คิว jobs ใช้ร่วมกันทุกชนิด"""
    kind: Literal["chat", "analyse"]
    session_id: UUID
