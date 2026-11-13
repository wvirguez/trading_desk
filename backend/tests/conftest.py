from collections.abc import AsyncIterator, Callable

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.db import build_engine, get_session
from app.main import app

SessionOverride = Callable[[], AsyncIterator[AsyncSession]]


def session_override_for(url: str) -> SessionOverride:
    """Crea una dependencia `get_session` contra una URL concreta."""

    async def _override() -> AsyncIterator[AsyncSession]:
        engine = build_engine(url)
        try:
            async with async_sessionmaker(engine)() as session:
                yield session
        finally:
            await engine.dispose()

    return _override


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def use_test_db() -> None:
    """Apunta `get_session` a la base de datos de tests (TEST_DATABASE_URL)."""
    app.dependency_overrides[get_session] = session_override_for(get_settings().test_database_url)


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Sesión contra TEST_DATABASE_URL con `ohlcv_bars` y `trade_signals` vacías (D20).

    `instruments` se conserva: sus filas vienen de la migración de seed.
    """
    engine = build_engine(get_settings().test_database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await session.execute(text("TRUNCATE ohlcv_bars, trade_signals"))
            await session.commit()
            yield session
            await session.rollback()
    finally:
        await engine.dispose()
