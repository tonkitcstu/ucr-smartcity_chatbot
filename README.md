# UCR Smartcity Chatbot — น้องเมือง

บอทบน LINE OA (UCR / TONKIT Lab) ที่ชวนคนในชุมชนเล่าเรื่องสภาพแวดล้อมและ
โครงสร้างพื้นฐานแถวบ้าน แล้วสกัดออกมาเป็นรายงานพร้อมพิกัด ปลายทางคือหมุดบน
แผนที่ให้ทีมออกแบบเมืองใช้ตัดสินใจว่าควรปรับปรุงตรงไหนก่อน

กฎการเขียนโค้ดอยู่ใน [`CLAUDE.md`](CLAUDE.md) — **อ่านก่อนแก้โค้ด**

## ต้องมีอะไรบ้าง

| ของ | ใช้ทำอะไร |
|---|---|
| Python 3.12 ขึ้นไป + [uv](https://docs.astral.sh/uv/) | รันแอป ลง dependency จาก `uv.lock` |
| PostgreSQL | ของถาวร: ผู้แจ้ง ใบ ข้อความ รายงาน |
| Redis | ของชั่วคราว: ข้อความที่ยังไม่ตอบ state ของใบ คิวงาน |
| key ของ Gemini | AI ที่คุยกับผู้แจ้งและทำรายงาน |
| LINE OA ช่องทดสอบ | ช่องทางแชท — ห้ามใช้ช่องจริงตอนพัฒนา |

แอปต่อ PostgreSQL ตอนเปิด ต่อไม่ได้แอปไม่ขึ้น

## ตั้งเครื่องใหม่

```bash
uv sync

cp .env.example .env        # แล้วเติมค่าจริง (คำอธิบายอยู่ในไฟล์)

createdb ucr-chat-v2-alpha
psql ucr-chat-v2-alpha -f schema.sql      # ครั้งเดียว — ฐานเดียวกับ DATABASE_URL ใน .env
```

`schema.sql` ไม่มี `IF NOT EXISTS` รันซ้ำบนฐานที่มีตารางแล้วจะ error

ไม่ใช้ uv: `pip install -r requirements.txt` ได้ dependency ชุดเดียวกัน
(ไฟล์นี้สร้างจาก `uv.lock` — แก้ dependency ที่ `pyproject.toml` แล้วสร้างใหม่ด้วยคำสั่งที่หัวไฟล์)

## รัน

```bash
uv run uvicorn app.main:app --reload
```

เปิดครั้งแรกบนฐานเปล่า แอปใส่ model กับ prompt ตั้งต้นลง PostgreSQL ให้เอง

เช็คว่าขึ้นครบ:

```bash
curl -i http://localhost:8000/health
```

อยู่ครบตอบ 200 ขาดตัวใดตัวหนึ่งตอบ 503 และบอกตัวที่ขาด

```json
{"database": true, "redis": true, "worker": true, "sweeper": true}
```

ต่อ LINE: `ngrok http 8000` แล้วตั้ง webhook ของช่องทดสอบเป็น `https://<ngrok>/webhook/line`

## ทางเข้าที่มี

| ทาง | ทำอะไร | ใครเรียกได้ |
|---|---|---|
| `POST /webhook/line` | รับ event จาก LINE | ตรวจด้วยลายเซ็นของ LINE |
| `GET /health` | PostgreSQL · Redis · worker · sweeper ยังอยู่ไหม | ทุกคน |
| `GET /api/dashboard/reports` | รายงาน ใหม่ไปเก่า กรองด้วย `date` · `tag` · `limit` | JWT |
| `GET /api/dashboard/attachments/{attachment_id}` | ไฟล์รูปของรายงาน | JWT |
| `GET /api/dashboard/transcripts/{session_id}` | บทสนทนาทั้งใบ | JWT |

3 เส้นใต้ `/api/dashboard` ต้องส่ง `Authorization: Bearer <jwt>` ที่เซ็นด้วย `SECRET_KEY`
ตัวเดียวกับใน `.env` — backend ของทีมออกแบบเป็นคนออก token เราแค่ตรวจ
ไม่ตั้ง `SECRET_KEY` = 3 เส้นนี้ตอบ 503 · token ผิดหรือไม่ส่ง = 401

## test

```bash
createdb ucr_nongmuang_test     # ครั้งเดียว
uv run pytest
```

test ใช้ฐาน `ucr_nongmuang_test` กับ Redis db 15 แยกจากของที่แอปใช้
**test ล้างฐานและ Redis db นั้นทุกรอบ** — อย่าชี้ `TEST_DATABASE_URL` หรือ `TEST_REDIS_URL` ไปที่ของจริง

test ที่ยิง Gemini จริงถูกข้าม เปิดด้วย `LIVE_AI=1 uv run pytest`

## ของที่ไม่ขึ้น git

- `uploads/` — รูปที่ผู้แจ้งส่งมา
- `.env` — ค่าจริง
- `local/` — สมุดจดส่วนตัว

## เอกสาร

- `docs/requirements/` — ความต้องการ ข้อจำกัด user story
- `docs/designs/` — แบบที่ใช้ตอนสร้างแต่ละส่วน
