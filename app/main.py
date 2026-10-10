import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import line
from app.clients import database, redis
from app.core.config import WORKER_ENABLED
from app.workers import worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    await database.connect()
    await redis.connect()
    worker_task = asyncio.create_task(worker.run()) if WORKER_ENABLED else None
    try:
        yield
    finally:
        if worker_task:
            worker_task.cancel()
        await redis.close()
        await database.close()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

app.include_router(line.router)
