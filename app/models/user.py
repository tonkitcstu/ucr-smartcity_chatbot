from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class User(BaseModel):
    """ผู้แจ้งที่กดยอมรับ PDPA แล้ว — มี User = ยอมรับแล้ว"""

    user_id: UUID
    line_user_id: str
    pdpa_accepted_at: datetime
