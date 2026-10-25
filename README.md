# UCR Smartcity Chatbot — น้องเมือง

บอทบน LINE OA (UCR / TONKIT Lab) ที่ชวนคนในชุมชนเล่าเรื่องสภาพแวดล้อมและ
โครงสร้างพื้นฐานแถวบ้าน แล้วสกัดออกมาเป็นรายงานพร้อมพิกัด ปลายทางคือหมุดบน
แผนที่ให้ทีมออกแบบเมืองใช้ตัดสินใจว่าควรปรับปรุงตรงไหนก่อน

กฎการเขียนโค้ดอยู่ใน [`CLAUDE.md`](CLAUDE.md) — **อ่านก่อนแก้โค้ด**

## ต้องมีอะไรบ้าง

| ของ | ใช้ทำอะไร |
|---|---|
| Python 3.12 ขึ้นไป + [uv](https://docs.astral.sh/uv/) | รันแอป ลง dependency จาก `uv.lock` |
| PostgreSQL + PostGIS | ของถาวร: ผู้แจ้ง ใบ ข้อความ รายงาน · `schema.sql` เปิด extension `postgis` (macOS: `brew install postgis`) |
| Redis | ของชั่วคราว: ข้อความที่ยังไม่ตอบ state ของใบ คิวงาน |
| key ของ Gemini | AI ที่คุยกับผู้แจ้งและทำรายงาน |
| LINE OA ช่องทดสอบ | ช่องทางแชท — ห้ามใช้ช่องจริงตอนพัฒนา |

แอปต่อ PostgreSQL ตอนเปิด ต่อไม่ได้แอปไม่ขึ้น

ไม่อยากลงเอง: ข้ามไป [รันด้วย Docker](#รันด้วย-docker) ต้องมีแค่ Docker

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

## รันด้วย Docker

ต้องมีแค่ Docker — ไม่ต้องลง Python, PostgreSQL หรือ Redis เอง

```bash
cp .env.example .env            # เติมค่าจริง และตั้ง POSTGRES_PASSWORD
docker compose up -d --build
docker compose ps               # ทั้ง 3 ต้องเป็น healthy
curl -i http://localhost:8000/health
```

ได้ 3 container

| container | มีอะไร | ข้อมูลอยู่ที่ volume |
|---|---|---|
| `app` | แอป (FastAPI + worker + sweeper ใน process เดียว) | `uploads` — รูป |
| `postgres` | PostgreSQL 18 + PostGIS · สร้างฐาน `ucr-chat-v2-alpha` และรัน `schema.sql` ตอนฐานยังว่าง | `pgdata` |
| `redis` | Redis 8 | `redisdata` |

ใน container เรียกกันด้วยชื่อ service — compose ใส่ `DATABASE_URL` กับ `REDIS_URL` ทับค่าใน `.env` ให้
`postgres` กับ `redis` ไม่เปิด port ออกนอกเครื่อง

แต่ละตัวมีไฟล์ของตัวเอง `docker-compose.yml` ที่รากรวม 3 ตัวเข้าด้วยกันและบอกว่าแอปต้องรอฐานพร้อมก่อน

```
docker-compose.yml              ทั้งระบบ
docker/
  app/Dockerfile                image ของแอป
  app/docker-compose.yml
  postgres/Dockerfile           postgres:18 + PostGIS
  postgres/docker-compose.yml
  redis/docker-compose.yml
```

| คำสั่ง | ทำอะไร |
|---|---|
| `docker compose up -d --build` | แก้โค้ดแล้ว — สร้าง image ใหม่และเปิด |
| `docker compose up -d` | แก้แค่ค่าใน `.env` |
| `docker compose logs -f app` | ดู log ของแอป |
| `docker compose restart app` | เปิดแอปใหม่ |
| `docker compose up -d --build --no-deps app` | สร้างและเปิดแอปใหม่ตัวเดียว ไม่แตะฐาน |
| `docker compose stop redis` · `docker compose start redis` | ปิด / เปิดทีละตัว |
| `docker compose down` | ปิดทั้งระบบ ข้อมูลยังอยู่ |
| `docker compose down -v` | ปิดและ**ลบฐาน รูป และ Redis ทั้งหมด** |

ต้องรู้:

- `POSTGRES_PASSWORD` ใช้ตอนสร้างฐานครั้งแรกเท่านั้น แก้ทีหลังฐานยังใช้รหัสเดิม แอปจะต่อไม่ได้
- ชื่อชุดตั้งไว้ในไฟล์ (`name: ucr-smartcity_chatbot`) ทุกไฟล์ — volume กับเครือข่ายเป็นชุดเดิมเสมอ ไม่ว่าโฟลเดอร์ชื่ออะไรหรือสั่งจากไฟล์ไหน
- เปิดจากไฟล์ของตัวเดียวได้ สั่งจากราก repo และต้องใส่ `--env-file .env`:
  `docker compose --env-file .env -f docker/app/docker-compose.yml up -d --build`
  แบบนี้แอปไม่รอฐาน ต้องเปิด `postgres` กับ `redis` ไว้ก่อน และ compose จะเตือนว่าเจอ orphan containers (คือตัวที่ไม่อยู่ในไฟล์นั้น) — **อย่าใส่ `--remove-orphans`** มันจะลบ container ของตัวอื่น
- Redis ดับแล้วกลับมา worker ไม่กลับมาเอง `/health` ตอบ 503 — สั่ง `docker compose restart app`
- port 8000 ถูกใช้อยู่: ตั้ง `APP_PORT` ใน `.env`

## ทางเข้าที่มี

| ทาง | ทำอะไร | ใครเรียกได้ |
|---|---|---|
| `POST /webhook/line` | รับ event จาก LINE | ตรวจด้วยลายเซ็นของ LINE |
| `GET /health` | PostgreSQL · Redis · worker · sweeper ยังอยู่ไหม | ทุกคน |
| `GET /api/dashboard/reports` | รายงาน ใหม่ไปเก่า กรองด้วย `date` · `tag` · `limit` | กุญแจ API |
| `GET /api/dashboard/attachments/{attachment_id}` | ไฟล์รูปของรายงาน | กุญแจ API |
| `GET /api/dashboard/transcripts/{session_id}` | บทสนทนาทั้งใบ | กุญแจ API |

ทุกเส้นใต้ `/api/dashboard` ต้องส่ง header `Authorization: Bearer <กุญแจ>` ที่ตรงกับ `DASHBOARD_API_KEY` ใน `.env`
— ทีมออกแบบได้กุญแจดอกเดียวกัน · ไม่ตั้ง `DASHBOARD_API_KEY` = ทุกเส้นตอบ 503 · กุญแจผิดหรือไม่ส่ง = 401
สเปกเต็มพร้อม curl: `docs/designs/09-modules/h7-dashboard-api.md`

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
- `docs/v2-0alpha/` — แบบของรุ่นที่รันอยู่ ไล่ตามโค้ดจริงตั้งแต่ข้อความเข้าจนเป็นรายงาน
