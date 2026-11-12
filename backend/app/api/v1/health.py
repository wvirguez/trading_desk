"""`GET /api/v1/health`: estado del backend y de la base de datos."""

from importlib.metadata import version as pkg_version
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.schemas.health import HealthSchema

router = APIRouter(tags=["system"])

APP_VERSION = pkg_version("quant-agentic-backend")


async def probe_database(session: AsyncSession) -> tuple[bool, str | None]:
    """Devuelve (base de datos accesible, versión de timescaledb o None)."""
    try:
        await session.execute(text("SELECT 1"))
        result = await session.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")
        )
        ts_version: str | None = result.scalar_one_or_none()
    except (SQLAlchemyError, OSError, TimeoutError):
        return False, None
    return True, ts_version


@router.get(
    "/health",
    response_model=HealthSchema,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthSchema}},
)
async def health(
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HealthSchema:
    db_ok, ts_version = await probe_database(session)
    healthy = db_ok and ts_version is not None
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthSchema(
        status="ok" if healthy else "degraded",
        version=APP_VERSION,
        database="ok" if db_ok else "error",
        timescaledb=ts_version,
    )
