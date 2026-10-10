"""ตัววิเคราะห์: เรียก AI → ตรวจรูปแบบ → บันทึก ai_calls → คืนรายงาน 0..n"""

from uuid import UUID

from pydantic import ValidationError

from app.clients import ai, database
from app.models.ai import AiConfig
from app.models.context import ContextMessage
from app.models.report import Analysis, ReportDraft

ATTEMPTS = 3


async def analyse(session_id: UUID, config: AiConfig, messages: list[ContextMessage]) -> list[ReportDraft]:
    """ลองได้ ATTEMPTS ครั้ง ส่ง messages ชุดเดิม · แกะไม่ผ่าน → ai_calls error แล้วลองใหม่
    ไม่ผ่านครบทุกครั้ง → โยน error ต่อ (analyse_failed นอก happy path)"""
    model = await database.select_model(config.analyzer_model_id)
    for attempt in range(ATTEMPTS):
        reply = await ai.structured(model.name, messages, Analysis)
        try:
            analysis = Analysis.model_validate_json(reply.text)
        except ValidationError as error:
            await database.insert_ai_call(
                session_id, config.ai_config_id, "analyser", messages, reply, "error", str(error)
            )
            if attempt == ATTEMPTS - 1:
                raise
            continue
        await database.insert_ai_call(session_id, config.ai_config_id, "analyser", messages, reply)
        return analysis.reports
