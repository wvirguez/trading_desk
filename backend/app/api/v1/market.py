"""`GET /api/v1/market/ohlcv`: últimas velas de un instrumento."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.repositories import instruments as instruments_repo
from app.repositories import ohlcv as ohlcv_repo
from app.schemas.candle import CandleSchema
from app.schemas.enums import Timeframe

router = APIRouter(prefix="/market", tags=["market"])


@router.get(
    "/ohlcv",
    response_model=list[CandleSchema],
    responses={status.HTTP_404_NOT_FOUND: {"description": "Instrumento desconocido"}},
)
async def get_ohlcv(
    session: Annotated[AsyncSession, Depends(get_session)],
    symbol: Annotated[str, Query(min_length=1, description="Símbolo canónico, p. ej. BTC/USDT")],
    tf: Annotated[Timeframe, Query(description="Timeframe de las velas")],
    limit: Annotated[int, Query(ge=1, le=5000, description="Número de velas")] = 500,
) -> list[CandleSchema]:
    instrument = await instruments_repo.get_by_symbol(session, symbol)
    if instrument is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Instrumento desconocido: {symbol}"
        )
    return await ohlcv_repo.fetch_latest(session, instrument.id, tf, limit, symbol)
