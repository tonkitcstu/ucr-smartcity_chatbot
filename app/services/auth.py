"""ใครเป็นใคร — เช็คกุญแจ API ที่ทีมแดชบอร์ดแนบมาใน header `Authorization: Bearer <กุญแจ>`

กุญแจมีดอกเดียว อยู่ใน DASHBOARD_API_KEY ของ .env · ทีมแดชบอร์ดถือดอกเดียวกัน
กุญแจหลุด → เปลี่ยนค่าใน .env แล้วส่งดอกใหม่ให้เขา

ไฟล์นี้ไม่รู้จักรหัสสถานะ HTTP — บอกได้แค่ว่ากุญแจตรงไหม ส่วนจะตอบ 401 หรือ 503
เป็นเรื่องของ api/dashboard.py
"""

import secrets

from app.core import config


def is_valid_key(given: str | None) -> bool:
    # เทียบด้วย compare_digest ไม่ใช่ == เพราะ == หยุดทันทีที่เจอตัวแรกที่ต่าง เวลาที่ใช้จึงบอกใบ้ว่าเดาถูกไปกี่ตัวแล้ว
    # แปลงเป็น bytes ก่อน เพราะ compare_digest กับ str รับแค่ตัวอักษร ASCII
    if not given or not config.DASHBOARD_API_KEY:
        return False
    return secrets.compare_digest(given.encode(), config.DASHBOARD_API_KEY.encode())
