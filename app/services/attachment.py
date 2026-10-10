"""ไฟล์แนบ: ดาวน์โหลดรูปจาก LINE → เขียนลง uploads → บันทึก attachment"""

from app.clients import database, line
from app.core.config import UPLOADS_DIR
from app.models.attachment import Attachment
from app.models.message import Message


async def save(message: Message) -> Attachment:
    """ดาวน์โหลดด้วย line_message_id ทันที (TC9) · ไฟล์ชื่อ {message_id}.jpg"""
    content = await line.download_message_content(message.line_message_id)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    path = UPLOADS_DIR / f"{message.message_id}.jpg"
    path.write_bytes(content)
    return await database.insert_attachment(message.message_id, str(path))
