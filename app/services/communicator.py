"""ตัวคุย: เรียก AI → แกะคำตอบ ตรวจข้อความและคำบนปุ่ม → บันทึก ai_calls → คืนคำตอบ (ไม่รู้จัก LINE)"""

import unicodedata
from uuid import UUID

from app.clients import ai, database
from app.models.ai import AiConfig
from app.models.answer import ChatAnswer
from app.models.context import ContextMessage
from app.models.line import QuickReplyButton

# prompt ของตัวคุยห้ามตอบเกินนี้ต่อรอบ · LINE รับ reply ครั้งละไม่เกิน 5 ข้อความ
TEXTS_MAX = 5
# prompt ของตัวคุยห้ามคำบนปุ่มยาวเกินนี้ · LINE รับไม่เกิน 20 และนับแบบที่ตาเห็น (grapheme cluster)
LABEL_MAX = 20
# สระบน สระล่าง วรรณยุกต์ — เกาะกับตัวอักษรก่อนหน้า ตาเห็นรวมเป็นตัวเดียว (Unicode category)
MARKS = ("Mn", "Me")


async def chat(session_id: UUID, config: AiConfig, messages: list[ContextMessage]) -> ChatAnswer:
    """ai_calls เก็บคำตอบดิบทั้งก้อน · ข้อความหรือปุ่มผิดกติกา → status warning พร้อมเหตุ ผู้แจ้งยังได้คำตอบ
    แกะเป็น ChatAnswer ไม่ได้ หรือไม่เหลือข้อความให้ส่ง → ai_calls error แล้วโยน error ต่อ (นอก happy path)"""
    model = await database.select_model(config.chat_model_id)
    reply = await ai.chat(model.name, messages, ChatAnswer)
    try:
        answer = ChatAnswer.model_validate_json(reply.text)
        texts, text_warnings = check_texts(answer.texts)
    except ValueError as error:
        await database.insert_ai_call(
            session_id, config.ai_config_id, "communicator", messages, reply, "error", str(error)
        )
        raise
    buttons, button_warnings = check_labels(answer.buttons)
    warnings = [*text_warnings, *button_warnings]
    await database.insert_ai_call(
        session_id,
        config.ai_config_id,
        "communicator",
        messages,
        reply,
        "warning" if warnings else "ok",
        " · ".join(warnings) or None,
    )
    return ChatAnswer(texts=texts, buttons=buttons)


def check_texts(texts: list[str]) -> tuple[list[str], list[str]]:
    """ข้อความว่าง → ตัดทิ้ง · เกิน TEXTS_MAX → รวมส่วนที่เกินเข้าข้อความที่ TEXTS_MAX คั่นด้วยขึ้นบรรทัดใหม่ เนื้อหาไม่หาย
    คืนข้อความที่ส่งได้ + คำเตือน · ไม่เหลือข้อความเลย → ValueError"""
    kept = [text for text in texts if text.strip()]
    warnings = []
    if len(kept) < len(texts):
        warnings.append(f"ข้อความว่าง {len(texts) - len(kept)} ข้อความ ตัดทิ้ง")
    if not kept:
        raise ValueError("คำตอบไม่มีข้อความให้ส่ง")
    if len(kept) > TEXTS_MAX:
        warnings.append(f"ตอบ {len(kept)} ข้อความ เกิน {TEXTS_MAX} รวมส่วนที่เกินเข้าข้อความที่ {TEXTS_MAX}")
        kept = [*kept[: TEXTS_MAX - 1], "\n".join(kept[TEXTS_MAX - 1 :])]
    return kept, warnings


def check_labels(buttons: list[QuickReplyButton]) -> tuple[list[QuickReplyButton], list[str]]:
    """คำบนปุ่มยาวเกิน LABEL_MAX → ตัดเหลือ LABEL_MAX ตัวแรก ปุ่มยังอยู่ · คำว่าง → ตัดปุ่มนั้นทิ้ง
    ความยาวนับแบบที่ตาเห็น · คืนปุ่มที่ส่งได้ + คำเตือนของปุ่มที่ถูกแก้"""
    kept, warnings = [], []
    for button in buttons:
        label = button.label.strip()
        if not label:
            warnings.append(f"ปุ่ม {button.type}: คำบนปุ่มว่าง ตัดปุ่มทิ้ง")
            continue
        length = seen_length(label)
        if length > LABEL_MAX:
            warnings.append(f"ปุ่ม {button.type}: คำบนปุ่มยาว {length} เกิน {LABEL_MAX} ตัดเหลือ {LABEL_MAX} ตัวแรก")
            label = cut_seen(label, LABEL_MAX)
        kept.append(QuickReplyButton(type=button.type, label=label))
    return kept, warnings


def seen_length(text: str) -> int:
    """ความยาวแบบที่ตาเห็น — สระบน สระล่าง วรรณยุกต์ ไม่นับ · เลขที่ได้ไม่น้อยกว่าของ LINE เช่น "น้ำ" ได้ 2 LINE นับ 1"""
    return sum(1 for char in text if unicodedata.category(char) not in MARKS)


def cut_seen(text: str, limit: int) -> str:
    """limit ตัวแรกแบบที่ตาเห็น · สระและวรรณยุกต์ของตัวสุดท้ายยังอยู่"""
    seen = 0
    for index, char in enumerate(text):
        if unicodedata.category(char) not in MARKS:
            seen += 1
            if seen > limit:
                return text[:index]
    return text
