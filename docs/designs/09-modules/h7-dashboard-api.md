# H7 dashboard API — JSON จากฐานใหม่ (schema.sql)

ทุกเส้นขึ้นต้น `/api/dashboard` · ต้องมี `Authorization: Bearer <jwt>`

## fail ที่ใช้ร่วมกันทุกเส้น

401 ไม่มี token / token ผิด / หมดอายุ / ไม่มี sub
```json
{"detail": "Could not validate credentials"}
```

503 ไม่ได้ตั้ง SECRET_KEY
```json
{"detail": "SECRET_KEY is not set"}
```

---

## 1. GET /reports?date=2026-10-10&tag=น้ำท่วม&limit=20

200
```json
[
  {
    "report_id": "6f1c0a2e-...",
    "session_id": "a41d77c3-...",
    "user_id": "b7d2e9a1-...",
    "desc": "ฝนตกทีไรน้ำท่วมหน้าบ้าน สูงเกือบเข่า",
    "tags": ["น้ำท่วม", "ท่อระบายน้ำ"],
    "lat": 13.75,
    "lng": 100.5,
    "attachments": [
      {"attachment_id": "0c9e...", "url": "/api/dashboard/attachments/0c9e..."}
    ],
    "started_at": "2026-10-10T09:05:00+07:00",
    "created_at": "2026-10-10T09:20:00+07:00"
  }
]
```

200 ไม่มีรายงานที่ตรง
```json
[]
```

422 date ไม่ใช่ YYYY-MM-DD / limit นอก 1–200
```json
{"detail": [{"loc": ["query", "date"], "msg": "Input should be a valid date"}]}
```

## 2. GET /attachments/{attachment_id}

200 — ไฟล์รูป `Content-Type: image/jpeg` (ไม่ใช่ JSON)

404 ไม่มีแถวใน attachments / ไฟล์ไม่อยู่บนดิสก์
```json
{"detail": "Attachment not found"}
```

422 attachment_id ไม่ใช่ uuid
```json
{"detail": [{"loc": ["path", "attachment_id"], "msg": "Input should be a valid UUID"}]}
```

## 3. GET /transcripts/{session_id}

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
    "attachment": null
  },
  {
    "message_id": "22bb...",
    "role": "user",
    "type": "image",
    "content": null,
    "lat": null,
    "lng": null,
    "attachment": {"attachment_id": "0c9e...", "url": "/api/dashboard/attachments/0c9e..."}
  },
  {
    "message_id": "33cc...",
    "role": "assistant",
    "type": "text",
    "content": "ท่วมสูงประมาณไหนคะ",
    "lat": null,
    "lng": null,
    "attachment": null
  },
  {
    "message_id": "44dd...",
    "role": "user",
    "type": "location",
    "content": null,
    "lat": 13.75,
    "lng": 100.5,
    "attachment": null
  }
]
```

404 ไม่มี session นี้
```json
{"detail": "Transcript not found"}
```

422 session_id ไม่ใช่ uuid
```json
{"detail": [{"loc": ["path", "session_id"], "msg": "Input should be a valid UUID"}]}
```
