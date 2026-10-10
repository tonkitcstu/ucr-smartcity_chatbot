import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import line
from app.clients import database, redis
from app.core.config import WORKER_ENABLED
from app.workers import sweeper, worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    await database.connect()
    await redis.connect()
    tasks = [asyncio.create_task(worker.run()), asyncio.create_task(sweeper.run())] if WORKER_ENABLED else []
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await redis.close()
        await database.close()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

app.include_router(line.router)
