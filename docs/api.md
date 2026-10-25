# API ทั้งหมด — 6 เส้น

ตัวแปรใน Postman: `{{base}}` = ที่อยู่ของเครื่องที่รันแอป (เครื่องตัวเอง `http://localhost:8000`) · `{{key}}` = ค่า `DASHBOARD_API_KEY` ใน `.env`
หน้าตา JSON ของแต่ละเส้นและ curl: `docs/designs/09-modules/h7-dashboard-api.md`

| # | เส้น | ทำอะไร | ใครเรียกได้ |
|---|---|---|---|
| 1 | `POST {{base}}/webhook/line` | รับข้อความและ event จาก LINE | LINE เท่านั้น (ตรวจลายเซ็นของ LINE) |
| 2 | `GET {{base}}/health` | PostgreSQL · Redis · worker · sweeper ยังทำงานไหม | ทุกคน |
| 3 | `GET {{base}}/api/dashboard/reports` | รายงาน ใหม่ไปเก่า กรองได้ | กุญแจ API |
| 4 | `GET {{base}}/api/dashboard/reports/:report_id` | รายงานใบเดียว | กุญแจ API |
| 5 | `GET {{base}}/api/dashboard/attachments/:attachment_id` | ไฟล์รูป | กุญแจ API |
| 6 | `GET {{base}}/api/dashboard/transcripts/:session_id` | บทสนทนาทั้งใบ | กุญแจ API |

## กุญแจ API (เส้น 3–6)

header `Authorization: Bearer <กุญแจ>`
Postman: แท็บ Authorization ของ collection → Auth Type `Bearer Token` → Token `{{key}}` · คำขอข้างในเลือก `Inherit auth from parent`

| ได้ | เมื่อ |
|---|---|
| 401 `{"detail": "Invalid API key"}` | ไม่แนบกุญแจ / กุญแจผิด / ไม่มีคำว่า `Bearer` นำหน้า |
| 503 `{"detail": "DASHBOARD_API_KEY is not set"}` | เครื่องนั้นยังไม่ได้ตั้ง `DASHBOARD_API_KEY` |

## 3. รายงาน — ตัวกรอง

ทุกตัวไม่ใส่ก็ได้ · ใส่หลายตัว รายงานต้องตรงทุกตัว · วันนับจากเวลาที่รายงานถูกสร้าง (`created_at`) ตามเวลาไทย

| ตัวกรอง | ค่า | ความหมาย |
|---|---|---|
| `date` | `YYYY-MM-DD` | สร้างในวันนั้น |
| `start_date` | `YYYY-MM-DD` | สร้างตั้งแต่วันนั้น นับวันนั้นด้วย |
| `end_date` | `YYYY-MM-DD` | สร้างจนถึงวันนั้น นับวันนั้นด้วย |
| `tag` | ข้อความ | มีป้ายนี้ ตรงทั้งคำ |
| `severity` | `low` · `medium` · `high` | ความรุนแรงเท่านี้ |
| `limit` | 1–200 · ค่าตั้งต้น 20 | เอากี่ใบ นับจากใบใหม่สุด |

วางใน Postman ได้เลย:

```
{{base}}/api/dashboard/reports
{{base}}/api/dashboard/reports?date=2026-10-25
{{base}}/api/dashboard/reports?start_date=2026-10-01
{{base}}/api/dashboard/reports?end_date=2026-10-25
{{base}}/api/dashboard/reports?start_date=2026-10-01&end_date=2026-10-31
{{base}}/api/dashboard/reports?tag=น้ำท่วม
{{base}}/api/dashboard/reports?severity=high
{{base}}/api/dashboard/reports?limit=50
{{base}}/api/dashboard/reports?tag=น้ำท่วม&severity=high&start_date=2026-10-01&end_date=2026-10-31&limit=200
```

| ได้ | เมื่อ |
|---|---|
| 200 รายการรายงาน · ไม่มีที่ตรง = `[]` | ปกติ |
| 422 | วันไม่ใช่ `YYYY-MM-DD` / `severity` ไม่ใช่สามค่านั้น / `limit` นอก 1–200 |

## 4–6. เส้นที่ใส่รหัส

`:ชื่อ` ใน Postman คือตัวแปรในที่อยู่ — ใส่ค่าในตาราง Path Variables ของแท็บ Params

```
{{base}}/api/dashboard/reports/:report_id
{{base}}/api/dashboard/attachments/:attachment_id
{{base}}/api/dashboard/transcripts/:session_id
```

| รหัส | เอามาจาก |
|---|---|
| `report_id` | `report_id` ในรายการรายงาน |
| `attachment_id` | `attachments[].attachment_id` ในรายงาน หรือ `attachment.attachment_id` ในบทสนทนา |
| `session_id` | `session_id` ในรายงาน |

| ได้ | เมื่อ |
|---|---|
| 200 | เจอ · เส้น attachments ได้ไฟล์รูป `image/jpeg` ไม่ใช่ JSON |
| 404 `Report not found` · `Attachment not found` · `Transcript not found` | ไม่มีรหัสนี้ (attachments: หรือไฟล์ไม่อยู่บนดิสก์) |
| 422 | รหัสไม่ใช่ uuid |
