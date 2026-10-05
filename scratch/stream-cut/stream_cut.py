import json
import os
from dotenv import load_dotenv
import httpx
from pathlib import Path
import datetime

load_dotenv()

URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
KEY = os.getenv("GEMINI_API_KEY")

lazy_prompt = "เล่าเรื่องน้ำท่วมในหมู่บ้าน ยาว ~600 คำ"

# จำลองที่ Worker จะส่งจริง: system prompt + session ที่คุยมา + buffer ใหม่
NONGMUANG_PROMPT = (Path(__file__).parent / "nongmuang_prompt.md").read_text()
nongmuang_messages = [
    {"role": "system", "content": NONGMUANG_PROMPT},
    {"role": "user", "content": "สวัสดีครับ"},
    {"role": "assistant", "content": "สวัสดีค่ะ เมืองเป็นแชทบอทของทีมออกแบบเมือง UCR ค่ะ มีเรื่องสภาพพื้นที่แถวบ้านอยากเล่าไหมคะ"},
    {"role": "user", "content": "น้ำท่วมหน้าบ้านครับ ฝนตกทีไรท่วมทุกที"},
    {"role": "assistant", "content": "ท่วมทุกครั้งที่ฝนตกเลย ลำบากแย่เลยค่ะ ปกติน้ำท่วมสูงประมาณไหน แล้วนานกี่ชั่วโมงกว่าจะลดคะ"},
    {"role": "user", "content": "ประมาณข้อเท้า รอครึ่งวันกว่าจะลด เดินไปตลาดไม่ได้เลย"},
]
MODEL = "gemini-3.5-flash-lite"
PRICE_IN = 0.30 / 1_000_000     # ดอลลาร์ต่อ 1 token
PRICE_OUT = 2.50 / 1_000_000


def print_cost(input_tokens, output_tokens):
    cost_in = input_tokens * PRICE_IN
    cost_out = output_tokens * PRICE_OUT
    print(f"  input  {input_tokens:>6} token  ${cost_in:.6f}")
    print(f"  output {output_tokens:>6} token  ${cost_out:.6f}")
    print(f"  รวม                 ${cost_in + cost_out:.6f}")

def no_stream (prompt):
    res = httpx.post(
        url=URL,
        headers={
            "Authorization": f"Bearer {KEY}"
            },
        json = {
            "model":MODEL,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout = 60,
    )

    data = res.json()
    print(data["choices"][0]["message"]["content"])
    print(data["usage"])

def simple_stream (prompt):
    with httpx.stream(
        "POST",
        URL,
        headers={"Authorization": f"Bearer {KEY}"},
        json={
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
            "stream_options": {"include_usage": True},
        },
        timeout=60,
    ) as res:
        for line in res.iter_lines():
            if not line.startswith("data: "):
                continue                      
            if line == "data: [DONE]":
                break                         

            chunk = json.loads(line[len("data: "):])   # ตัด "data: " ออก แล้วแปลงเป็น dict
            text = chunk["choices"][0]["delta"].get("content", "")
            tokens = chunk["usage"]["completion_tokens"]
            print(tokens, text[:20])

def cut_stream(messages, after):
    count = 0
    last_tokens = 0
    last_input = 0
    fulltext = ""
    with httpx.stream(
        "POST",
        URL,
        headers={"Authorization": f"Bearer {KEY}"},
        json={
            "model": MODEL,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        },
        timeout=60,
    ) as res:
        for line in res.iter_lines():
            if not line.startswith("data: "):
                continue
            if line == "data: [DONE]":
                break

            chunk = json.loads(line[len("data: "):])
            fulltext += chunk["choices"][0]["delta"].get("content", "")
            last_tokens = chunk["usage"]["completion_tokens"]
            last_input = chunk["usage"]["prompt_tokens"]
            count += 1
            if count >= after:
                break
    print(fulltext)
    print(datetime.datetime.now().strftime("%H:%M:%S"), "ตัดที่", count, "chunk")
    print_cost(last_input, last_tokens)

# ปล่อยจนจบ (after เยอะ ๆ = ไม่ตัด) แล้วตัดที่ 1 chunk
cut_stream(nongmuang_messages, 999)
cut_stream(nongmuang_messages, 1)