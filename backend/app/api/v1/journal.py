"""`GET /api/v1/journal`: señales emitidas frente a su resultado simulado (D133, D142)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.schemas.journal import JournalSchema
from app.services import paper as paper_service
from app.services.backtest import InstrumentNotFoundError

router = APIRouter(prefix="/journal", tags=["journal"])


@router.get(
    "",
    response_model=JournalSchema,
    responses={status.HTTP_404_NOT_FOUND: {"description": "Instrumento desconocido"}},
)
async def get_journal(
    session: Annotated[AsyncSession, Depends(get_session)],
    symbol: Annotated[str | None, Query(description="Filtra por símbolo")] = None,
    limit: Annotated[int, Query(ge=1, le=500, description="Máximo de señales")] = 100,
) -> JournalSchema:
    """Entradas (recientes primero) y resumen estadístico. Solo lectura."""
    try:
        return await paper_service.get_journal(session, symbol, limit)
    except InstrumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
