"""Punto de entrada ASGI: `uv run uvicorn app.main:app --reload`."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.health import APP_VERSION
from app.api.v1.router import api_router
from app.core.db import get_engine


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield
    await get_engine().dispose()


app = FastAPI(title="QuantAgentic Terminal API", version=APP_VERSION, lifespan=lifespan)
app.include_router(api_router)
