"""รายงาน: บันทึกรายงานจากตัววิเคราะห์ + ผูกรูป"""

from uuid import UUID

from app.clients import database
from app.models.ai import AiConfig
from app.models.message import TranscriptMessage
from app.models.report import ReportDraft


async def save(
    session_id: UUID, config: AiConfig, drafts: list[ReportDraft], transcript: list[TranscriptMessage]
) -> None:
    """แปลงเลขป้ายกลับด้วยกติกาเดียวกับ prompt.build_analyse_context:
    รูป n = แถว image ลำดับที่ n · ตำแหน่ง n = แถว location ลำดับที่ n"""
    images = [message for message in transcript if message.type == "image"]
    locations = [message for message in transcript if message.type == "location"]
    for draft in drafts:
        pin = locations[draft.location - 1] if draft.location else None
        lat, lng = (pin.lat, pin.lng) if pin else (None, None)
        report_id = await database.insert_report(session_id, config.ai_config_id, draft.desc, draft.tags, lat, lng)
        await database.link_attachments(report_id, [images[n - 1].attachment_id for n in draft.images])
