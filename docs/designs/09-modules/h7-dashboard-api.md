# API แดชบอร์ด — JSON จากฐานใหม่ (schema.sql)

ทุกเส้นขึ้นต้น `/api/dashboard` · ต้องมี header `Authorization: Bearer <กุญแจ>`
กุญแจมีดอกเดียว คือค่า `DASHBOARD_API_KEY` ใน `.env` ของเรา · ทีมแดชบอร์ดได้ดอกเดียวกัน
กุญแจหลุด → เปลี่ยนค่าใน `.env` แล้วส่งดอกใหม่ให้ทีมแดชบอร์ด

## ก่อนลอง curl

```sh
BASE=http://localhost:8000      # เครื่องจริงใช้ที่อยู่ของเครื่องนั้น
KEY=$(grep '^DASHBOARD_API_KEY=' .env | cut -d= -f2-)
```

คำสั่ง `KEY=` อ่านกุญแจจาก `.env` ของเครื่องตัวเองโดยไม่พิมพ์ออกจอ · ต้องรันที่โฟลเดอร์โปรเจกต์

## fail ที่ใช้ร่วมกันทุกเส้น

401 ไม่ได้แนบกุญแจ / กุญแจผิด
```json
{"detail": "Invalid API key"}
```

503 ไม่ได้ตั้ง DASHBOARD_API_KEY
```json
{"detail": "DASHBOARD_API_KEY is not set"}
```

---

## 1. GET /reports

รายงานใหม่ไปเก่า (เรียงตาม `created_at`) · ตัวกรองทุกตัวไม่ใส่ก็ได้ · ใส่หลายตัว รายงานต้องตรงทุกตัว

| ตัวกรอง | ค่า | ความหมาย |
|---|---|---|
| `tag` | ข้อความ | มีป้ายนี้ ตรงทั้งคำ (`น้ำ` ไม่ตรงกับ `น้ำท่วม`) |
| `severity` | `low` · `medium` · `high` | ความรุนแรงเท่านี้ |
| `date` | `YYYY-MM-DD` | สร้างในวันนั้นตามเวลาไทย |
| `start_date` | `YYYY-MM-DD` | สร้างตั้งแต่วันนั้นตามเวลาไทย นับวันนั้นด้วย |
| `end_date` | `YYYY-MM-DD` | สร้างถึงวันนั้นตามเวลาไทย นับวันนั้นด้วย |
| `limit` | 1–200 · ค่าตั้งต้น 20 | เอากี่ใบ นับจากใบใหม่สุด |

`start_date` ใส่ตัวเดียวได้ (ตั้งแต่วันนั้นถึงวันนี้) · `end_date` ใส่ตัวเดียวได้ (ทุกใบจนถึงวันนั้น) · `start_date` เลย `end_date` ได้ `[]`

```sh
# ทั้งหมด 20 ใบล่าสุด
curl -sS "$BASE/api/dashboard/reports" -H "Authorization: Bearer $KEY"

# ตามป้าย · ภาษาไทยต้องใช้ --data-urlencode
curl -sS -G "$BASE/api/dashboard/reports" -H "Authorization: Bearer $KEY" \
  --data-urlencode "tag=น้ำท่วม"

# ตามความรุนแรง
curl -sS -G "$BASE/api/dashboard/reports" -H "Authorization: Bearer $KEY" \
  -d severity=high

# วันเดียว
curl -sS -G "$BASE/api/dashboard/reports" -H "Authorization: Bearer $KEY" \
  -d date=2026-10-24

# ช่วงวัน
curl -sS -G "$BASE/api/dashboard/reports" -H "Authorization: Bearer $KEY" \
  -d start_date=2026-10-01 -d end_date=2026-10-24

# รวมกัน: น้ำท่วม รุนแรงมาก ตลอดเดือนตุลาคม 200 ใบ
curl -sS -G "$BASE/api/dashboard/reports" -H "Authorization: Bearer $KEY" \
  --data-urlencode "tag=น้ำท่วม" -d severity=high \
  -d start_date=2026-10-01 -d end_date=2026-10-31 -d limit=200
```

200
```json
[
  {
    "report_id": "6f1c0a2e-...",
    "session_id": "a41d77c3-...",
    "user_id": "b7d2e9a1-...",
    "desc": "ฝนตกทีไรน้ำท่วมหน้าบ้าน สูงเกือบเข่า ต้องเดินอ้อมไปปากซอย",
    "tags": ["น้ำท่วม", "ท่อระบายน้ำ"],
    "severity": "medium",
    "affected_groups": ["pedestrians", "residents"],
    "time_periods": ["morning"],
    "place": "หน้าวัด",
    "lat": 13.75,
    "lng": 100.5,
    "attachments": [
      {"attachment_id": "0c9e...", "url": "/api/dashboard/attachments/0c9e..."}
    ],
    "started_at": "2026-10-10T09:05:00+07:00",
    "created_at": "2026-10-10T11:20:00+07:00"
  }
]
```

| ช่อง | ความหมาย |
|---|---|
| `user_id` | รหัสผู้แจ้งของบอท ไม่ใช่ LINE ID |
| `desc` | สรุปเรื่องที่ตัววิเคราะห์เขียน |
| `place` | ตำแหน่งตามคำของผู้แจ้ง · ไม่ได้บอกเป็นคำ = `null` |
| `lat` `lng` | หมุดที่ผู้แจ้งปัก · ไม่ได้ปัก = `null` |
| `started_at` | เวลาที่เปิดบทสนทนา · รายงานจากบทสนทนาเดียวกันได้เวลาเดียวกัน · บอททักไปก่อน = เวลาที่บอททัก |
| `created_at` | เวลาที่รายงานถูกสร้าง (หลังบทสนทนาถูกปิด) |

`severity`

| ค่า | ความหมาย |
|---|---|
| `high` | อันตรายต่อร่างกายหรือสุขภาพ หรือใช้ชีวิตประจำวันไม่ได้ เช่น น้ำเข้าบ้าน ไปทำงานไม่ได้ เคยมีคนเจ็บ |
| `medium` | ลำบาก ต้องอ้อม ต้องเสียเวลาหรือเสียเงิน แต่ยังใช้ชีวิตได้ |
| `low` | ไม่สะดวกหรือรำคาญ หรือนาน ๆ เกิดครั้ง |

`affected_groups` (ว่างได้)

| ค่า | ความหมาย |
|---|---|
| `elderly` | ผู้สูงอายุ |
| `children` | เด็ก นักเรียน |
| `disabled` | คนพิการ คนป่วย หรือคนที่เดินไม่สะดวก |
| `pedestrians` | คนเดินเท้า |
| `drivers` | คนขับรถ ขี่มอเตอร์ไซค์ หรือปั่นจักรยาน |
| `workers` | คนทำงานหรือค้าขายตรงนั้น |
| `residents` | คนที่อยู่บ้านแถวนั้น |

`time_periods` (ว่างได้)

| ค่า | ช่วง |
|---|---|
| `morning` | 06:00–10:00 |
| `midday` | 10:00–15:00 |
| `evening` | 15:00–19:00 |
| `night` | 19:00–06:00 |

200 ไม่มีรายงานที่ตรง
```json
[]
```

422 `date` `start_date` `end_date` ไม่ใช่ YYYY-MM-DD / `severity` ไม่ใช่สามค่านั้น / `limit` นอก 1–200
```json
{"detail": [{"loc": ["query", "severity"], "msg": "Input should be 'low', 'medium' or 'high'"}]}
```

## 2. GET /reports/{report_id}

```sh
curl -sS "$BASE/api/dashboard/reports/6f1c0a2e-..." -H "Authorization: Bearer $KEY"
```

200 — รายงานใบเดียว ช่องเหมือนหนึ่งใบใน `GET /reports` (ไม่ใช่ list)

404 ไม่มีรายงานนี้
```json
{"detail": "Report not found"}
```

422 report_id ไม่ใช่ uuid
```json
{"detail": [{"loc": ["path", "report_id"], "msg": "Input should be a valid UUID"}]}
```

## 3. GET /attachments/{attachment_id}

`url` ในรายงานกับในบทสนทนาชี้มาที่เส้นนี้

```sh
curl -sS "$BASE/api/dashboard/attachments/0c9e..." -H "Authorization: Bearer $KEY" -o photo.jpg
```

200 — ไฟล์รูป `Content-Type: image/jpeg` (ไม่ใช่ JSON)

404 ไม่มีแถวใน attachments / ไฟล์ไม่อยู่บนดิสก์
```json
{"detail": "Attachment not found"}
```

422 attachment_id ไม่ใช่ uuid
```json
{"detail": [{"loc": ["path", "attachment_id"], "msg": "Input should be a valid UUID"}]}
```

## 4. GET /transcripts/{session_id}

ข้อความทั้งบทสนทนาเรียงตามเวลา · `session_id` เอามาจากรายงาน

```sh
curl -sS "$BASE/api/dashboard/transcripts/a41d77c3-..." -H "Authorization: Bearer $KEY"
```

200
```json
[
  {
    "message_id": "11aa...",
    "role": "user",
    "type": "text",
    "content": "น้ำท่วมหน้าบ้านอีกแล้ว",
    "lat": null,
    "lng": null,
    "status": "answered",
    "attachment": null
  },
  {
    "message_id": "22bb...",
    "role": "user",
    "type": "image",
    "content": null,
    "lat": null,
    "lng": null,
    "status": "answered",
    "attachment": {"attachment_id": "0c9e...", "url": "/api/dashboard/attachments/0c9e..."}
  },
  {
    "message_id": "33cc...",
    "role": "assistant",
    "type": "text",
    "content": "ท่วมสูงประมาณไหนคะ",
    "lat": null,
    "lng": null,
    "status": "answered",
    "attachment": null
  },
  {
    "message_id": "44dd...",
    "role": "user",
    "type": "location",
    "content": null,
    "lat": 13.75,
    "lng": 100.5,
    "status": "answered",
    "attachment": null
  },
  {
    "message_id": "55ee...",
    "role": "user",
    "type": "sticker",
    "content": "cony, sally, Staring, hi, wave, Hello",
    "lat": null,
    "lng": null,
    "status": "answered",
    "attachment": null
  }
]
```

`type` เป็น `text` · `image` · `location` · `sticker`
`status` เป็น `answered` (บอทตอบแล้ว) · `pending` (ยังรอบอทตอบ) · `skipped` (บอทไม่ตอบ เช่น ส่งตอนถูกพัก · ตัววิเคราะห์ไม่เห็น)
แถว `sticker`: `content` คือคำที่ LINE ใช้บรรยายสติกเกอร์ (ไม่ใช่คำที่ผู้แจ้งพิมพ์) · LINE ไม่ส่งมาก็เป็น `null`

404 ไม่มี session นี้
```json
{"detail": "Transcript not found"}
```

422 session_id ไม่ใช่ uuid
```json
{"detail": [{"loc": ["path", "session_id"], "msg": "Input should be a valid UUID"}]}
```
