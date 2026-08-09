"""หน้าแผนที่ให้ทีมออกแบบเปิดดู — อ่านอย่างเดียว ไม่มีอะไรเขียนกลับ

หน้าเว็บเป็นไฟล์เดียวใน static/ ที่ไปเรียก /api/dashboard/reports เอาเอง
ไฟล์นี้จึงมีแค่ 3 ทาง: หน้าเว็บ, ข้อมูล, และรูป

**ล็อกทั้ง router** (issue #139) ข้างในคือเรื่องที่ชาวบ้านเล่า + พิกัดบ้าน + รูปบ้าน
ของจริง เคยเปิดโล่งให้ใครที่รู้ URL อ่านได้หมด

คนเข้ามีสองพวก ด่านเดียวกันรับทั้งคู่ (ดู services/auth.py):
  ทีมแดชบอร์ด  `Authorization: Bearer <jwt>` — เหมือนเดิมทุกอย่าง ไม่ต้องแก้ฝั่งเขา
  คนในทีมเรา    Basic auth ที่เบราว์เซอร์เด้งให้เอง แล้วมันแนบให้ทุก request
                ของ origin เดียวกัน **รวม `<img src>` ของรูปด้วย** หน้าเว็บจึง
                ไม่ต้องแก้อะไร (ของเดิมบน main รูปบังคับ JWT เลยใช้ `<img>`
                ตรง ๆ ไม่ได้ ต้อง fetch แล้วแปลงเป็น Object URL เอง)
"""

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.api.deps import get_db, guard
from app.clients import media, storage
from app.core.config import BASE_DIR

router = APIRouter(dependencies=[Depends(guard)])

PAGE = BASE_DIR / "app" / "static" / "dashboard.html"
VENDOR = (BASE_DIR / "app" / "static" / "vendor").resolve()


@router.get("/dashboard")
async def page() -> FileResponse:
    return FileResponse(PAGE)


@router.get("/dashboard/vendor/{name:path}")
async def vendor(name: str) -> FileResponse:
    """Leaflet ที่เก็บไว้เองในเครื่อง — **เดิมโหลดจาก unpkg.com**

    ไม่ใช่แค่ "แผนที่ไม่ขึ้น" ถ้าโหลดไม่ได้ สคริปต์ในหน้าเรียก `L.map()` ก่อน
    `fetch()` ข้อมูล พอ `L` ไม่มีตัวตนมันโยน error ตรงนั้นแล้ว**ทั้งบล็อกที่เหลือ
    ไม่ทำงานเลย** — ไม่ดึงข้อมูล ไม่ขึ้นรายการใบ ไม่มีตัวกรอง และ `.catch()`
    ที่เตรียมข้อความ "ต่อกับเซิร์ฟเวอร์ไม่ได้" ไว้ก็ไม่มีวันได้ทำงาน
    ชาวบ้านไม่เห็นหน้านี้ แต่คนที่เห็นคือทีมออกแบบเมืองบนจอโปรเจกเตอร์

    เน็ตงานที่ช้า มี captive portal หรือบล็อก CDN = หน้าขาวทั้งหน้า
    ไทล์แผนที่ยังมาจากข้างนอกอยู่ (เก็บเองไม่ได้) แต่ไทล์ไม่มาแค่พื้นหลังเทา
    หมุดกับรายการใบยังอยู่ครบ

    `{name:path}` เพราะ leaflet.css อ้าง `images/marker-icon.png` ต่อจากตัวมันเอง
    เช็ค parents กันคนเดินย้อนขึ้นไปหยิบไฟล์นอกโฟลเดอร์
    """
    path = (VENDOR / name).resolve()
    if not path.is_file() or VENDOR not in path.parents:
        raise HTTPException(status_code=404, detail="ไม่มีไฟล์นี้")

    return FileResponse(path)


@router.get("/api/dashboard/reports")
async def reports(pool: asyncpg.Pool = Depends(get_db)) -> list[dict]:
    """ทุกใบที่เก็บไว้ พร้อมพิกัดและรายการรูป

    ส่งใบที่ไม่มีพิกัดมาด้วย **ตั้งใจ** — ใบพวกนั้นปักหมุดเองไม่ได้ ต้องให้ทีม
    มาปักมือทีหลัง ถ้ากรองทิ้งตรงนี้มันจะหายไปจากสายตาทุกคนตลอดกาล
    """
    return await storage.list_reports(pool)


@router.get("/api/dashboard/image/{image_id}")
async def image(image_id: int, pool: asyncpg.Pool = Depends(get_db)) -> FileResponse:
    """รูปของใบนั้น อ้างด้วย id ของรูป ไม่ใช่ path — ข้างนอกไม่ต้องรู้ว่าไฟล์อยู่ไหน"""
    key = await storage.image_key(pool, image_id)
    if key is None:
        raise HTTPException(status_code=404, detail="ไม่มีรูปนี้")

    path = media.local_file(key)
    if path is None:
        # แถวมีแต่ไฟล์หาย — เกิดได้ถ้าย้ายเครื่องแล้วสำรองมาแต่ฐานข้อมูล
        raise HTTPException(status_code=404, detail="มีรูปในระบบแต่หาไฟล์ไม่เจอ")

    return FileResponse(path, media_type="image/jpeg")
