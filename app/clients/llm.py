"""คุยกับโมเดล — **ไฟล์เดียวในโปรเจกต์ที่รู้ว่าเราใช้เจ้าไหน**

ตอนนี้เป็น Gemini แต่ต่อผ่าน**ช่องทางที่พูดภาษา OpenAI** ของ Google เอง
(`.../v1beta/openai/`) เลยใช้ไลบรารี `openai` ได้ตรง ๆ ทั้ง tool calling
และ `reasoning_effort` — ไม่ต้องมีโค้ดแปลงร่างให้ใครดูแล

ที่ไม่ใช้ REST ดั้งเดิมของ Google (`models/<model>:generateContent`) เพราะรูปร่าง
ข้อความมันคนละแบบ ถ้าใช้อันนั้น `services/survey.py` ที่ส่ง messages/tools
แบบ OpenAI มาจะต้องถูกรื้อตาม ทั้งที่มันไม่ควรต้องรู้เลยว่าปลายทางเป็นเจ้าไหน

วันเปลี่ยนเจ้า: แก้ MODEL กับ base_url ตรงนี้ที่เดียว
"""

import json

from openai import AsyncOpenAI
from app.core.config import API_ENDPOINT, API_KEY, REASONING_EFFORT

# ชื่อโมเดลอยู่ที่เดียว เดิมพิมพ์ซ้ำ 3 ที่ แล้ววันเปลี่ยนก็ลืมที่ใดที่หนึ่งเสมอ
#
# **ที่ใช้ lite เพราะโควตา ไม่ใช่เพราะมันดีกว่า** — key ฟรีให้ `gemini-flash-latest`
# แค่ 20 ครั้ง/วัน/โปรเจกต์ ซึ่งหมดตั้งแต่ยังทดสอบไม่ทันจบ (หนึ่งตาของบทสนทนา
# กินได้ถึง 3 ครั้ง เพราะวนเรียก tool ได้ 3 รอบ — ดู MAX_TOOL_ROUNDS)
# วันเปิดบิลแล้วค่อยเปลี่ยนกลับเป็น gemini-flash-latest ตรงนี้บรรทัดเดียว
MODEL = "gemini-flash-lite-latest"

# คิดหนักหน่อยได้ ตาหนึ่งของบทสนทนาไม่ได้เกิดถี่ขนาดต้องประหยัด
# และของที่เราขอจากมันคือการ**ไม่ปั้นเรื่องที่ชาวบ้านไม่ได้พูด** ซึ่งพลาดแล้วแพง
#
# **วัดเทียบ low/medium/high แล้ว 8 ส.ค. 69** (บทสนทนาเดียวกัน 6 ตา 11 call):
#
#     low     70,539 token · 2.4 วิ/ตา · คิด 0 token
#     medium  79,282 token · 5.2 วิ/ตา · คิด 5,735 token
#     high    86,078 token · 6.9 วิ/ตา · คิด 9,097 token
#
# เก็บข้อมูลลงใบได้ **ครบ 8/8 ช่องเท่ากันทั้งสามระดับ** และบทสนทนาที่ไม่มีข้อมูลเลย
# ก็**ไม่ปั้นเรื่องเพิ่มทั้งสามระดับ** (0/7 ช่อง) — ยังไม่เจอหลักฐานว่า low โง่ลง
# แต่วัดมาแค่บทสนทนาละหนึ่งรอบ ยังบางเกินกว่าจะเปลี่ยนค่าตั้งต้นของตัวที่กันการปั้นเรื่อง
#
# **ที่แพงจริงไม่ใช่การคิด แต่คือ prompt ที่ส่งซ้ำทุก call** — 88% ของ token ที่ high
# และ 98.6% ที่ low เป็น prompt ล้วน ๆ prompt caching จึงคุ้มกว่าการลด effort มาก
EFFORT = {"reasoning_effort": REASONING_EFFORT}

client = AsyncOpenAI(
    api_key=API_KEY,
    base_url=API_ENDPOINT,
)


def _usage(completion) -> dict:
    """`{"calls": 1, "tokens": N}` — **เลขจริงจากผู้ให้บริการ ไม่ใช่ค่าประมาณ**

    ของนี้ติดกลับมาทุก response อยู่แล้ว เดิมเราทิ้งทุกครั้ง ทั้งที่มันคือตัวเดียว
    ที่บอกได้ว่าตาหนึ่งกินไปเท่าไหร่จริง ๆ — หนึ่งตาห่างกันได้ 5 เท่า (หัวคงที่ ~9k
    บวกประวัติที่โตขึ้นเรื่อย ๆ) นับเป็นจำนวนครั้งอย่างเดียวเลยหยาบเกินกว่าจะกันอะไรได้

    คืนเป็น dict ธรรมดา คนนอกไฟล์นี้จะได้ไม่ต้องรู้จักหน้าตา object ของ OpenAI
    หาไม่เจอ = 0 ไม่ใช่ error — ตัวนับพังไม่ควรทำให้ชาวบ้านคุยไม่ได้

    **ต้องใช้ total_tokens เป็นหลัก ห้ามเอา prompt + completion เป็นตัวตั้ง**
    ฝั่ง Gemini ไม่นับ token ที่ใช้ "คิด" ไว้ใน completion_tokens และไม่ยอมบอกใน
    completion_tokens_details.reasoning_tokens ด้วย (ได้ 0 ทุกครั้งที่ลอง) มันโผล่
    เฉพาะใน total_tokens — วัดจริงแล้วต่างกันถึง 9,097 token ต่อบทสนทนาที่ effort=high
    บวกเองจากสองช่องนั้นจะนับขาดไปราว 11% ซึ่งคือส่วนที่แพงที่สุดของการเปิดให้มันคิด
    """
    usage = getattr(completion, "usage", None)
    if usage is None:
        return {"calls": 1, "tokens": 0}

    total = getattr(usage, "total_tokens", None)
    if total is None:
        total = (getattr(usage, "prompt_tokens", 0) or 0) + (
            getattr(usage, "completion_tokens", 0) or 0
        )

    return {"calls": 1, "tokens": total or 0}


async def get_playground(message: str) -> str:
    """ยิงเข้าโมเดลตรง ๆ ไม่มีความจำ ไม่มีเครื่องมือ — ไว้เช็คว่า key กับ endpoint ใช้ได้"""

    completion = await client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": message}],
        extra_body=EFFORT,
    )

    return completion.choices[0].message.content


async def chat(messages: list[dict]) -> tuple[str, dict]:
    """Same model as the playground, but takes a full message history.

    คืน `(ข้อความ, usage)` — ตัวหลังเอาไปให้ `services/quota.py` นับ
    """

    completion = await client.chat.completions.create(
        model=MODEL,
        messages=messages,
        extra_body=EFFORT,
    )

    return completion.choices[0].message.content, _usage(completion)


def _no_nulls(value):
    """ทิ้งช่องที่เป็น null ออกให้หมด ก่อนส่งกลับเข้าโมเดล

    ฝั่ง Google ไม่รับ null **แม้แต่ช่องที่ตัวมันเองเพิ่งส่งมา** ตอบกลับมาว่า
    `Value is not a struct: null` ซึ่งไม่ได้บอกเลยว่าช่องไหน
    (ของที่มันแถมมาเป็น null: content, refusal, audio, annotations, function_call)
    """
    if isinstance(value, dict):
        return {k: _no_nulls(v) for k, v in value.items() if v is not None}
    return value


async def chat_tools(messages: list[dict], tools: list[dict]) -> dict:
    """Chat, letting the model call our tools.

    Returns a plain dict so nothing outside this file has to know what an
    OpenAI object looks like:

        {"content": "...", "tool_calls": [...], "usage": {"calls": 1, "tokens": N}}

    `_raw` ที่ติดมาในแต่ละ call เป็นของภายในไฟล์นี้ **คนนอกห้ามอ่าน** — ดู tool_exchange
    """

    completion = await client.chat.completions.create(
        model=MODEL,
        messages=messages,
        tools=tools,
        extra_body=EFFORT,
    )

    message = completion.choices[0].message
    return {
        "usage": _usage(completion),
        "content": message.content or "",
        "tool_calls": [
            {
                "id": call.id,
                "name": call.function.name,
                "arguments": json.loads(call.function.arguments or "{}"),
                # เก็บก้อนดิบไว้ทั้งอัน เพราะข้างในมี thought_signature ที่ต้องส่งคืน
                "_raw": _no_nulls(call.model_dump()),
            }
            for call in (message.tool_calls or [])
        ],
    }


def tool_exchange(tool_calls: list[dict], result: str) -> list[dict]:
    """The two messages the model expects back after it called a tool:
    what it asked for, and what it got. Same `result` for every call.

    **ต้องส่งก้อนเดิมที่มันให้มาคืนไปทั้งก้อน ห้ามประกอบขึ้นใหม่จาก name/arguments**
    โมเดลที่คิดก่อนตอบจะแนบ `thought_signature` (ก้อน base64 ที่เราอ่านไม่ออก)
    มากับ tool call ทุกอัน แล้ว**บังคับ**ให้ส่งคืนตอนคุยรอบถัดไป ไม่งั้นตอบ 400:
    `Function call is missing a thought_signature in functionCall parts`

    เดิมตรงนี้ประกอบข้อความขึ้นใหม่จาก name กับ arguments ซึ่งอ่านแล้วดูครบดี
    แต่ลายเซ็นหล่นหายไปเงียบ ๆ ผลคือ**ทุกบทสนทนาที่ AI เก็บข้อมูลจะตายรอบที่สอง**
    คือรอบที่เราบอกมันว่าเก็บแล้วและยังขาดอะไร — ชาวบ้านเห็นแค่ข้อความขอโทษ
    ทั้งที่เขาเพิ่งเล่าเรื่องจบไปหมาด ๆ

    `_raw` ว่างเมื่อไหร่ค่อยประกอบเอง เผื่อวันเปลี่ยนไปเจ้าที่ไม่มีลายเซ็น
    """

    asked = {
        "role": "assistant",
        "tool_calls": [
            call.get("_raw")
            or {
                "id": call["id"],
                "type": "function",
                "function": {
                    "name": call["name"],
                    "arguments": json.dumps(call["arguments"], ensure_ascii=False),
                },
            }
            for call in tool_calls
        ],
    }
    got = [
        {"role": "tool", "tool_call_id": call["id"], "content": result}
        for call in tool_calls
    ]
    return [asked] + got