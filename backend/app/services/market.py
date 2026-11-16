"""Servicio de mercado: lista de instrumentos y estructura de mercado."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.quant.data import candles_to_frame
from app.quant.structure import analyze_structure
from app.repositories import instruments as instruments_repo
from app.repositories import ohlcv as ohlcv_repo
from app.schemas.enums import Timeframe
from app.schemas.instrument import InstrumentSchema
from app.schemas.quant import MarketStructureResult
from app.services.backtest import InstrumentNotFoundError, InsufficientDataError


async def list_instruments(session: AsyncSession) -> list[InstrumentSchema]:
    """Devuelve todos los instrumentos ordenados por id."""
    rows = await instruments_repo.list_all(session)
    return [instruments_repo.to_schema(row) for row in rows]


async def get_instruments(session: AsyncSession) -> list[InstrumentSchema]:
    """Alias para compatibilidad con la API."""
    return await list_instruments(session)


async def get_structure(
    session: AsyncSession,
    symbol: str,
    timeframe: Timeframe,
    n: int = 3,
) -> MarketStructureResult:
    """Calcula la estructura de mercado para un símbolo y timeframe.

    Reutiliza `candles_to_frame` y `analyze_structure` del núcleo cuantitativo.
    Lanza `InstrumentNotFoundError` si el símbolo no existe.
    Lanza `InsufficientDataError` si hay menos de `2n + 1` velas.
    Lanza `ValueError` si `n` no está en 1..10.
    """
    if not 1 <= n <= 10:
        raise ValueError("n debe estar entre 1 y 10")

    instrument = await instruments_repo.get_by_symbol(session, symbol)
    if instrument is None:
        raise InstrumentNotFoundError(symbol)

    candles = await ohlcv_repo.fetch_latest(session, instrument.id, timeframe, 5000, symbol)
    if len(candles) < 2 * n + 1:
        raise InsufficientDataError(symbol, timeframe.value, len(candles), 2 * n + 1)

    frame = candles_to_frame(candles)
    return analyze_structure(frame, n)
