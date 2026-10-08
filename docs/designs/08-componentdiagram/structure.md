# โครงไฟล์ — happy path (S1–S8)

มีไฟล์เท่าที่ happy path เรียกใช้ ภาพอยู่ใน `structure.puml` (ชั้น) กับ `message-flow.puml` (ลำดับเวลา)

## กฎ

1. ชั้นเรียงตามทางไหลลง: `main` → `api/` → `controllers/` · `workers/` → `services/` → `clients/`
2. สมองตัดสินใจ แต่ไม่คุยกับของนอกบ้านเอง — communicator คืนคำตอบ ให้ worker เป็นคน reply
3. ไฟล์เล็ก ชื่อบอกหน้าที่
4. service แบ่งตามสิ่งของ · client หนึ่งไฟล์ต่อของนอกบ้านหนึ่งอย่าง
5. ชื่ออังกฤษ · comment บอกว่าทำอะไร · state ใครใช้คนนั้นเปลี่ยน

ลูกศรชี้ลงอย่างเดียว ชั้นล่างไม่ import ชั้นบน

## docker compose

| service | หน้าที่ |
|---|---|
| `app` | FastAPI + worker + sweeper เป็น asyncio task ใน process เดียว |
| `postgres` | ของถาวร — รัน `schema.sql` กับ `seed.sql` ตอน init |
| `redis` | ของชั่วคราว — buffer, ประวัติที่คุยมา, state, คิวงาน |

volume `uploads/` เก็บรูป

## ไฟล์

```
Dockerfile
docker-compose.yml
schema.sql                      ตารางตาม 07-dbdiagram
seed.sql                        ai_configs แถวแรก: model + prompt ของ communicator และ analyser

app/
  main.py                       Boss — เปิด FastAPI, ต่อ database/redis, ปลุก worker กับ sweeper

  core/
    config.py                   อ่าน .env

  api/                          เส้นทาง (path) — รับ request แล้วส่งต่อให้ controller
    line.py                     POST /webhook/line
    dashboard.py                GET  /api/dashboard/reports

  controllers/                  สมองที่ request ปลุก
    line.py                     เช็คลายเซ็น แกะ event: follow → การ์ด PDPA · postback → ยอมรับ ·
                                message → เช็ค PDPA → บันทึก → ต่อ buffer + เวลาข้อความล่าสุด →
                                          ถ้า IDLE: IDLE→BUFFERING + ใบสั่งงานคุย · ถ้า BUFFERING อยู่แล้ว: ไม่ใส่ใบใหม่  [S1–S4]
    dashboard.py                เช็ค JWT → อ่านรายงาน → รูปแบบ API เดิม ไม่มี LINE ID  [S8]

  workers/                      สมองเบื้องหลัง ไม่มี request ปลุก
    worker.py                   หยิบใบสั่งงาน แยกเป็น asyncio task ต่อใบ
                                  งานคุย: รอเงียบ 3 วิ → BUFFERING→PROCESSING → loading animation → เก็บรูป →
                                          communicator → reply LINE → บันทึกคำตอบบอท → ตอบแล้ว → PROCESSING→IDLE  [S2 S6]
                                  งานวิเคราะห์: analyser → บันทึกรายงาน 0..n → session วิเคราะห์แล้ว  [S7]
    sweeper.py                  ทุก 1 นาที: ปิด session ที่เงียบเกิน 10 นาที → ใบสั่งงานวิเคราะห์  [S7]

  services/                     เครื่องมือกลาง แบ่งตามสิ่งของ
    pdpa.py                     การ์ด PDPA (ถ้อยคำตายตัว TC7), ยอมรับแล้วหรือยัง, บันทึกการยอมรับ
    pdpa_card.json              ตัวการ์ด Flex
    session.py                  หา/สร้าง session, buffer, ประวัติที่คุยมา, state, เวลาข้อความล่าสุด, ปิด session
    job.py                      ใบสั่งงาน: ใส่งานคุย, ใส่งานวิเคราะห์, หยิบงาน
    attachment.py               ดาวน์โหลดรูปจาก LINE → เขียนลง uploads/ → บันทึก attachment
    prompt.py                   อ่าน ai_config ล่าสุด, ประกอบ messages ของ communicator / analyser
    communicator.py             ตัวคุย: เรียก AI แบบ stream → บันทึก ai_calls → คืนคำตอบ (ไม่รู้จัก LINE)
    analyser.py                 ตัววิเคราะห์: เรียก AI → ตรวจรูปแบบ → บันทึก ai_calls → คืนรายงาน 0..n
    report.py                   บันทึกรายงาน + ผูกรูป, อ่านรายงานเป็นรูปแบบ API เดิม
    auth.py                     แกะ JWT (มีอยู่แล้ว)

  clients/                      ภาษาของของนอกบ้าน หนึ่งไฟล์ต่อหนึ่งอย่าง
    database.py                 SQL ทั้งหมด
    redis.py                    Redis
    line.py                     ลายเซ็น, reply, loading animation, ดาวน์โหลดรูป
    ai.py                       OpenAI SDK → Gemini

  models/                       pydantic ที่ส่งระหว่างชั้น
    message.py                  ข้อความที่แกะจาก event แล้ว
    job.py                      ใบสั่งงาน
    report.py                   รายงานจาก analyser, รายงานรูปแบบ API เดิม

uploads/                        รูป (ไม่ขึ้น git)
```

## ข้อความหนึ่งข้อความเดินผ่านไฟล์ไหน

ลำดับจากข้อ 1.1 ของ Idea

| # | เกิดอะไร | ไฟล์ |
|---|---|---|
| 1 | LINE ยิง webhook | `api/line.py` |
| 2 | เช็คลายเซ็น | `controllers/line.py` → `clients/line.py` |
| 3 | เช็คว่ายอมรับ PDPA แล้ว | `controllers/line.py` → `services/pdpa.py` → `clients/database.py` |
| 4 | แกะ event เป็นข้อความ | `controllers/line.py` → `models/message.py` |
| 5 | หา/สร้าง session + บันทึกข้อความ | `services/session.py` → `clients/database.py` |
| 6 | ต่อ buffer + เวลาข้อความล่าสุด = ตอนนี้ | `services/session.py` → `clients/redis.py` |
| 7 | ถ้า IDLE: IDLE → BUFFERING + ใส่ใบสั่งงานคุย · ถ้า BUFFERING อยู่แล้ว: ไม่ใส่ใบใหม่ | `services/session.py` · `services/job.py` → `clients/redis.py` |
| 8 | ตอบ 200 | `api/line.py` |
| 9 | หยิบใบสั่งงาน | `workers/worker.py` → `services/job.py` |
| 10 | รอเงียบ 3 วิ (ดูข้างล่าง), BUFFERING → PROCESSING | `workers/worker.py` → `services/session.py` |
| 10.1 | loading animation (60 วิ — หายเองตอนบอท reply) | `workers/worker.py` → `clients/line.py` |
| 11 | เก็บรูป | `services/attachment.py` → `clients/line.py` · `clients/database.py` |
| 12 | ประกอบ messages | `services/prompt.py` |
| 13 | เรียก AI + บันทึก ai_calls | `services/communicator.py` → `clients/ai.py` · `clients/database.py` |
| 14 | reply กลับ LINE | `workers/worker.py` → `clients/line.py` |
| 15 | บันทึกคำตอบบอท, ข้อความ → ตอบแล้ว, ล้าง buffer, ต่อประวัติ, PROCESSING → IDLE | `services/session.py` |

## รอเงียบ 3 วิ

controller ทุกข้อความ: ต่อ buffer + เขียนเวลาข้อความล่าสุด · ถ้า IDLE → BUFFERING + ใบสั่งงาน 1 ใบ · ถ้า BUFFERING อยู่แล้ว → ไม่ใส่ใบใหม่

worker: อ่านเวลาข้อความล่าสุด → ยังเงียบไม่ครบ 3 วิ ก็หลับเท่าที่ขาดแล้วอ่านใหม่ → ครบแล้ว BUFFERING → PROCESSING

| เวลา | เกิดอะไร |
|---|---|
| 00 | ข้อความ 1 → IDLE→BUFFERING ใส่ใบสั่งงาน |
| 02 | ข้อความ 2 → ต่อ buffer, เวลาล่าสุด = 02 |
| 03 | worker ตื่น เงียบมา 1 วิ → หลับต่อ 2 วิ |
| 05 | worker ตื่น เงียบครบ 3 วิ → PROCESSING |

ระวัง
- IDLE → BUFFERING ต้องเป็นคำสั่ง Redis คำสั่งเดียว (เช่น ให้ "ไม่มี key" = IDLE แล้วใช้ `SET ... NX`) — LINE ส่งรูปกับข้อความมาเกือบพร้อมกัน ถ้าเช็คแล้วค่อยเปลี่ยน สองข้อความเห็น IDLE ทั้งคู่ → ใบสั่งงาน 2 ใบ → ตอบสองรอบ
- worker แยกใบสั่งงานเป็น asyncio task ต่อใบ ไม่งั้นคน A หลับรอ 3 วิ คน B ต้องรอด้วย
- ข้อความที่มาหลังเปลี่ยนเป็น PROCESSING แล้ว = เรื่องตัด stream (ยังค้าง)

## log

ไม่มีตาราง log — `messages` เป็นบทสนทนาทั้งหมดอยู่แล้ว (ตกลงไว้ใน 07-dbdiagram)

| เก็บที่ | เรื่องอะไร |
|---|---|
| PSQL | เรื่องของผู้แจ้งและ AI — `messages`, `ai_calls` (request, คำตอบดิบ, token, สำเร็จ/error/ถูกตัด stream), `sessions` |
| stdout (`docker logs`) | เรื่องของระบบ — ลายเซ็นไม่ผ่าน, ดาวน์โหลดรูปไม่ได้, Redis ต่อไม่ติด, reply LINE ไม่สำเร็จ, sweeper ปิดไปกี่ใบ · ใช้ `logging` ของ Python ตั้งค่าครั้งเดียวใน `main.py` |

## ที่ Claude เสนอ (Idea ยังไม่มีกฎ)

**จับ error** — เท่าที่ S6 (ระบบขัดข้อง ผู้แจ้งยังได้คำตอบ และเรื่องไม่หาย) ต้องใช้:
`workers/worker.py` ครอบขั้น 13 ไว้ที่เดียว ถ้า AI พังหรือเกิน 50 วิ ให้ reply ข้อความสำรอง (TC7 ข้อยกเว้น 1)
ข้อความที่ผู้แจ้งส่งมาบันทึกลง PSQL ไปแล้วตั้งแต่ขั้น 5 เลยไม่หาย
ข้อความสำรองก็บันทึกลง `messages` เป็น role บอทด้วย ไม่งั้นตัววิเคราะห์อ่านบทสนทนาแล้วเหมือนบอทเงียบไป

## ยังค้าง

- analyser ตรวจรูปแบบแล้วลองซ้ำ 3 ครั้ง (ข้อ 1.1) — จะอยู่ใน `services/analyser.py`
- ตัด stream ตอนมีข้อความใหม่เข้ามาระหว่าง PROCESSING — นอก happy path
- S5 (บอกในแชทว่าบันทึกแล้ว) — นอก happy path: รายงานเกิดหลังปิด session แล้ว reply token หมด ต้องใช้ push (กินโควตา)

## ของเดิมที่ต้องเก็บกวาด

| ไฟล์ | สภาพ |
|---|---|
| `app/main.py` | import ไฟล์ที่ไม่มีแล้ว (`broadcast`, `dev`, `health`, `sweeper`, `db`) — บูตไม่ขึ้น |
| `app/api/line.py` | import ไฟล์ที่ไม่มีแล้ว (`burst`, `lock`, `quota`, `survey`) |
| `schema.sql` | ตารางของระบบเก่า |
| `app/services/auth.py` | ใช้ `jose` แต่ใน `pyproject.toml` ไม่มี |
