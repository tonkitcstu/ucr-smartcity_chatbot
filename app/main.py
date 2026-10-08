from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import line
from app.clients import database, redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    await database.connect()
    await redis.connect()
    try:
        yield
    finally:
        await redis.close()
        await database.close()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

app.include_router(line.router)
