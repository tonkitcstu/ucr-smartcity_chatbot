"""ตัวคุย: เรียก AI → แกะคำตอบ ตรวจคำบนปุ่ม → บันทึก ai_calls → คืนคำตอบ (ไม่รู้จัก LINE)"""

from uuid import UUID

from pydantic import ValidationError

from app.clients import ai, database
from app.models.ai import AiConfig
from app.models.answer import ChatAnswer
from app.models.context import ContextMessage
from app.models.line import QuickReplyButton

# prompt ของตัวคุยห้ามคำบนปุ่มยาวเกินนี้ · นับด้วย len() ซึ่งไม่น้อยกว่าที่ LINE นับ (LINE รับไม่เกิน 20)
LABEL_MAX = 20


async def chat(session_id: UUID, config: AiConfig, messages: list[ContextMessage]) -> ChatAnswer:
    """ai_calls เก็บคำตอบดิบทั้งก้อน · ปุ่มผิดกติกา → status warning พร้อมเหตุ ข้อความยังได้ตอบ
    แกะเป็น ChatAnswer ไม่ได้ → ai_calls error แล้วโยน error ต่อ (นอก happy path)"""
    model = await database.select_model(config.chat_model_id)
    reply = await ai.chat(model.name, messages, ChatAnswer)
    try:
        answer = ChatAnswer.model_validate_json(reply.text)
    except ValidationError as error:
        await database.insert_ai_call(
            session_id, config.ai_config_id, "communicator", messages, reply, "error", str(error)
        )
        raise
    buttons, warnings = check_labels(answer.buttons)
    await database.insert_ai_call(
        session_id,
        config.ai_config_id,
        "communicator",
        messages,
        reply,
        "warning" if warnings else "ok",
        " · ".join(warnings) or None,
    )
    return ChatAnswer(text=answer.text, buttons=buttons)


def check_labels(buttons: list[QuickReplyButton]) -> tuple[list[QuickReplyButton], list[str]]:
    """คำบนปุ่มยาวเกิน LABEL_MAX → ตัดเหลือ LABEL_MAX ตัวแรก ปุ่มยังอยู่ · คำว่าง → ตัดปุ่มนั้นทิ้ง
    คืนปุ่มที่ส่งได้ + คำเตือนของปุ่มที่ถูกแก้"""
    kept, warnings = [], []
    for button in buttons:
        label = button.label.strip()
        if not label:
            warnings.append(f"ปุ่ม {button.type}: คำบนปุ่มว่าง ตัดปุ่มทิ้ง")
            continue
        if len(label) > LABEL_MAX:
            warnings.append(f"ปุ่ม {button.type}: คำบนปุ่มยาว {len(label)} เกิน {LABEL_MAX} ตัดเหลือ {LABEL_MAX} ตัวแรก")
            label = label[:LABEL_MAX]
        kept.append(QuickReplyButton(type=button.type, label=label))
    return kept, warnings
