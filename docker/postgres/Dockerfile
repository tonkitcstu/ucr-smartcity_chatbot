# PostgreSQL 18 ตัวทางการ + PostGIS จาก repo ของ PostgreSQL เอง
# ไม่ใช้ image postgis/postgis เพราะมีแค่ amd64 — ตัวนี้ build ได้ทั้ง Apple Silicon และ EC2
FROM postgres:18

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-18-postgis-3 \
    && apt-get clean
