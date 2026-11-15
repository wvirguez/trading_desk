"""`GET /api/v1/signals/active`: señales aprobadas más recientes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.repositories import trade_signals as signals_repo
from app.schemas.enums import AssetClass
from app.schemas.signals import TradeSignalSchema

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("/active", response_model=list[TradeSignalSchema])
async def get_active_signals(
    session: Annotated[AsyncSession, Depends(get_session)],
    asset_class: Annotated[
        AssetClass | None, Query(description="Filtra por clase de activo")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200, description="Máximo de señales")] = 50,
) -> list[TradeSignalSchema]:
    """Señales `APPROVED`, de la más reciente a la más antigua."""
    return await signals_repo.list_active(session, asset_class, limit)
