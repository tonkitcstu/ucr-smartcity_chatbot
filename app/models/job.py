from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class Job(BaseModel):
    """ใบสั่งงานให้ worker"""
    kind: Literal["chat"]
    session_id: UUID
