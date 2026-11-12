"""Motor y sesiones async de SQLAlchemy 2.0."""

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    """Base declarativa de todos los modelos ORM."""


def build_engine(url: str) -> AsyncEngine:
    timeout = get_settings().db_connect_timeout_s
    return create_async_engine(url, pool_pre_ping=True, connect_args={"timeout": timeout})


@lru_cache
def get_engine() -> AsyncEngine:
    return build_engine(get_settings().database_url)


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Dependencia FastAPI: una sesión por petición."""
    async with get_sessionmaker()() as session:
        yield session
