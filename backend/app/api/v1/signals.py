"""`GET /api/v1/signals/active` y `POST /api/v1/signals/{id}/execute` (paper trading)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.repositories import trade_signals as signals_repo
from app.schemas.enums import AssetClass
from app.schemas.paper import OrderReceiptSchema
from app.schemas.signals import TradeSignalSchema
from app.services import paper as paper_service

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


@router.post(
    "/{signal_id}/execute",
    response_model=OrderReceiptSchema,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Señal desconocida"},
        status.HTTP_409_CONFLICT: {
            "description": "Señal no aprobada, ya ejecutada o vetada por las guardas de cartera"
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Identificador de señal inválido"},
    },
)
async def execute_signal(
    signal_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> OrderReceiptSchema:
    """Ejecuta una señal `APPROVED` en paper trading (simulado, sin costes ni slippage).

    Idempotente: una segunda llamada devuelve 409 sin crear otra orden (D136).
    """
    try:
        receipt = await paper_service.execute_signal(session, settings, signal_id)
    except paper_service.SignalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (paper_service.SignalNotExecutableError, paper_service.ExecutionVetoedError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await session.commit()
    return receipt
