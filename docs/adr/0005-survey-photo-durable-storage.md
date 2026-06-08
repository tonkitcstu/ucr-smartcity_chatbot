# เก็บรูป survey บน S3 — เลิก proxy สดจาก LINE CDN

## ปัญหา

ตอนนี้รูป (`q_photo`) ไม่ได้ถูกเก็บ byte ไว้ — `finalize_report` ปล่อย `image_path`
เป็น null รูปอยู่แค่เป็น proxy URL ที่ดึงสดจาก LINE CDN ทุกครั้ง LINE เก็บ content
ให้แค่ไม่กี่วันแล้วลบ → **รูปหายถาวร** พอใช้จริง (ต้อง deploy) จึงเก็บรูปไว้เองไม่ได้

## ตัดสินใจ

**เก็บ byte รูปบน S3 (object storage)** — ตอนรับรูปใน image handler ให้ download byte
จาก LINE แล้ว upload ขึ้น S3 เก็บ URL/key ลงคอลัมน์ `image_path` dashboard เสิร์ฟรูป
จาก S3 แทนการ proxy สด

เลือก S3 เพราะคงทน, แยกไฟล์ออกจาก DB, เป็นมาตรฐาน object storage และรองรับการโต
ในอนาคต (สอดคล้องกับแผนย้ายทั้งแอปขึ้น AWS)

## ผลที่ตามมา

- เพิ่มขั้น download + upload S3 ตอนรับรูป (logic ใหม่ที่ flow เดิมไม่มี)
- ต้องตั้ง bucket + credential (IAM) ตอน deploy
- ทีมยังไม่มีประสบการณ์ AWS/deploy → เป็นงานเรียนรู้ที่ต้องเผื่อเวลา/หาคนช่วย แยกต่างหาก

> ปริมาณเล็ก (~100–500KB/รูป ของจริงวัดได้ 112KB) ไม่ใช่ข้อจำกัดด้าน cost
