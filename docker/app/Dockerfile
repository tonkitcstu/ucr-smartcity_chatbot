# แอปตัวเดียว: FastAPI + worker + sweeper อยู่ใน process เดียวกัน (uvicorn app.main:app)
FROM python:3.13-slim

# uv ตัวเดียวกับที่ใช้บนเครื่อง dev — ลง dependency จาก uv.lock
COPY --from=ghcr.io/astral-sh/uv:0.11.23 /uv /uvx /bin/

ENV UV_NO_DEV=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app

# ลง dependency ก่อน copy โค้ด — แก้โค้ดแล้ว build ใหม่ไม่ต้องลงซ้ำ
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project

COPY app ./app

# ไม่รันเป็น root · uploads/ เป็นที่เดียวที่แอปเขียนไฟล์ (volume ใน docker-compose.yml)
RUN useradd --system --no-create-home app \
    && mkdir /app/uploads \
    && chown app /app/uploads
USER app

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
