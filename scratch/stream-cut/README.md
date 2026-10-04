# ตัด stream กลางทาง โดนคิด output กี่ token

การบ้านข้อ ง จากอาจารย์ — ถ้า Worker ตัด stream เพราะมีข้อความใหม่เข้ามา
เราเสียเงินเท่าที่รับมาแล้ว หรือเท่ากับที่โมเดลเขียนจนจบ

## วิธีทดลอง

`stream_cut.py` เรียกโมเดลด้วย prompt เดียวกัน (เล่าเรื่องยาว ~600 คำ)

- `full` ปล่อยจนจบ ดูว่าเต็ม ๆ ยาวเท่าไร
- `cut --after 30` รับ 30 chunk แล้วปิด connection

ผลทุกครั้งอยู่ใน `results.jsonl` พร้อมเวลา ไว้จับคู่กับ dashboard

## ผล Typhoon (2026-10-04 17:23)

| ครั้ง | mode | chunk ที่รับ | ตัวอักษร | เวลา |
|---|---|---|---|---|
| 1 | full | 1,332 | 2,280 | 8.7 วิ |
| 2 | full | 1,255 | 2,158 | 7.2 วิ |
| 3–5 | cut | 30 | 48 | 0.3–0.6 วิ |

- Typhoon **ไม่ส่ง usage** ตอน stream (ขอ `include_usage` แล้วได้ `null`)
  ตอนตัดก็ไม่ได้อยู่แล้ว — ตัวเลขที่ถูกคิดจริงต้องดูจาก dashboard เท่านั้น
- 1 chunk ≈ 1 token (ยังไม่ได้ยืนยันกับ usage)
- ถ้าคิดแค่ที่รับ: ตัด 3 ครั้ง ≈ 90 token / ถ้าคิดจนจบ: ≈ 3,900 token
  ต่างกัน ~40 เท่า ดู dashboard แล้วจะรู้ทันทีว่าเป็นแบบไหน

## ยังต้องทำ

- [ ] ดู dashboard Typhoon ช่วง 17:23 — output ของ 3 ครั้งที่ตัดเป็นเท่าไร
- [ ] ใส่ `GEMINI_API_KEY` ใน `.env` แล้วรันซ้ำกับ Gemini (prod จริง ตัวเลข Typhoon ใช้แทนไม่ได้)
  ```
  uv run python scratch/stream-cut/stream_cut.py gemini full --repeat 2
  uv run python scratch/stream-cut/stream_cut.py gemini cut --after 30 --repeat 3
  ```
  แล้วดู usage ใน AI Studio / Cloud Console ช่วงเวลานั้น
