"""schema.sql — ของที่ฐานต้องมีก่อนแอปเปิด · #208"""


async def test_postgis_is_installed(db):
    """1. รัน schema.sql แล้วฐานมี PostGIS — ถามเชิงพื้นที่ได้ (ระยะระหว่างสองจุดเป็นเมตร)"""
    assert await db.fetchval("SELECT extname FROM pg_extension WHERE extname = 'postgis'") == "postgis"

    metres = await db.fetchval(
        """
        SELECT ST_Distance(
            ST_SetSRID(ST_MakePoint(100.5018, 13.7563), 4326)::geography,
            ST_SetSRID(ST_MakePoint(100.5018, 13.7653), 4326)::geography
        )
        """
    )
    assert 900 < metres < 1100
