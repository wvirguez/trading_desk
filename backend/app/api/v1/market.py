"""Endpoints de mercado: instrumentos, velas y estructura."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.repositories import instruments as instruments_repo
from app.repositories import ohlcv as ohlcv_repo
from app.schemas.candle import CandleSchema
from app.schemas.enums import Timeframe
from app.schemas.instrument import InstrumentSchema
from app.schemas.quant import MarketStructureResult
from app.services.backtest import InstrumentNotFoundError, InsufficientDataError
from app.services.market import get_instruments, get_structure

router = APIRouter(prefix="/market", tags=["market"])


@router.get(
    "/instruments",
    response_model=list[InstrumentSchema],
)
async def list_instruments(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[InstrumentSchema]:
    """Lista todos los instrumentos ordenados por id."""
    return await get_instruments(session)


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


@router.get(
    "/structure",
    response_model=MarketStructureResult,
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Instrumento desconocido"},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Datos insuficientes o parámetros inválidos"
        },
    },
)
async def get_market_structure(
    session: Annotated[AsyncSession, Depends(get_session)],
    symbol: Annotated[str, Query(min_length=1, description="Símbolo canónico, p. ej. BTC/USDT")],
    tf: Annotated[Timeframe, Query(alias="tf", description="Timeframe de las velas")],
    limit: Annotated[int, Query(ge=1, le=5000, description="Número de velas a considerar")] = 500,
    n: Annotated[int, Query(ge=1, le=10, description="Ventana de swing (n)")] = 3,
) -> MarketStructureResult:
    """Calcula la estructura de mercado para un símbolo y timeframe.

    Usa `analyze_structure` sobre las últimas `limit` velas.
    - 404 si el símbolo no existe.
    - 422 si hay menos de `2n + 1` velas (mensaje con cantidades).
    - 422 si `n` está fuera de 1-10 (validación de FastAPI).
    """
    try:
        return await get_structure(session, symbol, tf, n)
    except InstrumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InsufficientDataError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
