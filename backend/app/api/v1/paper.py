"""`POST /api/v1/paper/refresh` y `GET /api/v1/paper/blotter` (D135)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.schemas.enums import OrderStatus
from app.schemas.paper import BlotterSchema, PaperRefreshResult
from app.services import paper as paper_service

router = APIRouter(prefix="/paper", tags=["paper"])


@router.post("/refresh", response_model=PaperRefreshResult)
async def post_refresh(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PaperRefreshResult:
    """Avanza las órdenes `PENDING_FILL`/`OPEN` con las velas ya ingeridas (idempotente)."""
    result = await paper_service.refresh_orders(session)
    await session.commit()
    return result


@router.get(
    "/blotter",
    response_model=BlotterSchema,
    responses={
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Parámetros de consulta inválidos"}
    },
)
async def get_blotter(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    order_status: Annotated[
        OrderStatus | None, Query(alias="status", description="Filtra por estado de la orden")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500, description="Máximo de órdenes")] = 100,
) -> BlotterSchema:
    """Cartera simulada y órdenes con PnL. Solo lectura: no avanza órdenes."""
    return await paper_service.get_blotter(session, settings, order_status, limit)
