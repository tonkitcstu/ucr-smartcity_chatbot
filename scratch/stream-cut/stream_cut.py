"""ทดลอง: เรียก AI แบบ stream แล้วตัดกลางทาง โดนคิด output กี่ token

ใช้:
  uv run python scratch/stream-cut/stream_cut.py typhoon full
  uv run python scratch/stream-cut/stream_cut.py typhoon cut --after 30 --repeat 5
  uv run python scratch/stream-cut/stream_cut.py gemini full

full = ปล่อยจนจบ ได้ usage จริงจาก API (stream_options include_usage)
cut  = รับ N chunk แล้วปิด connection — API ไม่ส่ง usage กลับมา
       ต้องไปดูใน dashboard ของ provider แล้วเทียบกับที่ได้รับจริง

ผลทุกครั้งต่อท้ายใน results.jsonl (มีเวลา ไว้จับคู่กับ dashboard)
"""

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

PROVIDERS = {
    "typhoon": {
        "base_url": "https://api.opentyphoon.ai/v1",
        "key_env": "TYPHOON_API_KEY",
        "model": "typhoon-v2.5-30b-a3b-instruct",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "key_env": "GEMINI_API_KEY",
        "model": "gemini-flash-lite-latest",
    },
}

# ยาวพอให้ตัดกลางทางได้ชัด ๆ
PROMPT = "เล่าเรื่องน้ำท่วมในหมู่บ้านแห่งหนึ่ง ยาวประมาณ 600 คำ เป็นภาษาไทย"
MAX_TOKENS = 1500

RESULTS = Path(__file__).parent / "results.jsonl"


def run_once(client, model, mode, after):
    started = time.time()
    stream = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": PROMPT}],
        max_tokens=MAX_TOKENS,
        stream=True,
        stream_options={"include_usage": True},
    )

    chunks = 0
    text = ""
    usage = None
    for chunk in stream:
        if chunk.usage:
            usage = chunk.usage.model_dump()
        if chunk.choices and chunk.choices[0].delta.content:
            chunks += 1
            text += chunk.choices[0].delta.content
        if mode == "cut" and chunks >= after:
            stream.close()
            break

    return {
        "at": datetime.now().isoformat(timespec="seconds"),
        "mode": mode,
        "chunks_received": chunks,
        "chars_received": len(text),
        "usage": usage,
        "seconds": round(time.time() - started, 2),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("provider", choices=PROVIDERS)
    p.add_argument("mode", choices=["full", "cut"])
    p.add_argument("--after", type=int, default=30, help="cut: ตัดหลังได้กี่ chunk")
    p.add_argument("--repeat", type=int, default=1)
    args = p.parse_args()

    cfg = PROVIDERS[args.provider]
    key = os.getenv(cfg["key_env"])
    if not key:
        raise SystemExit(f"ไม่มี {cfg['key_env']} ใน .env")
    client = OpenAI(base_url=cfg["base_url"], api_key=key)

    for _ in range(args.repeat):
        r = run_once(client, cfg["model"], args.mode, args.after)
        r = {"provider": args.provider, "model": cfg["model"], **r}
        print(json.dumps(r, ensure_ascii=False))
        with RESULTS.open("a") as f:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        time.sleep(3)  # กัน 429


if __name__ == "__main__":
    main()
