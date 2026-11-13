"""Acceso a `ohlcv_bars`: upsert idempotente y consultas de lectura."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ohlcv_bar import OhlcvBar
from app.schemas.candle import CandleSchema
from app.schemas.enums import Timeframe

BATCH_SIZE = 1000
_VALUE_COLUMNS = ("open", "high", "low", "close", "volume")


async def upsert_candles(
    session: AsyncSession, instrument_id: int, candles: Sequence[CandleSchema]
) -> int:
    """Inserta o actualiza velas por lotes de 1000 (D9) y devuelve las filas afectadas.

    Una fila existente solo se reescribe si algún valor cambia (`IS DISTINCT FROM`), de modo
    que repetir la operación con los mismos datos devuelve 0. Si hay velas repetidas en la
    entrada (misma clave), prevalece la última. No hace `commit`: lo decide quien llama.
    """
    unique = {(c.timeframe, c.ts): c for c in candles}
    rows = [
        {
            "instrument_id": instrument_id,
            "timeframe": c.timeframe.value,
            "ts": c.ts,
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume,
        }
        for c in unique.values()
    ]
    affected = 0
    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start : start + BATCH_SIZE]
        stmt = insert(OhlcvBar).values(batch)
        excluded = stmt.excluded
        stmt = stmt.on_conflict_do_update(
            index_elements=["instrument_id", "timeframe", "ts"],
            set_={col: excluded[col] for col in _VALUE_COLUMNS} | {"ingested_at": func.now()},
            where=tuple_(*(OhlcvBar.__table__.c[col] for col in _VALUE_COLUMNS)).is_distinct_from(
                tuple_(*(excluded[col] for col in _VALUE_COLUMNS))
            ),
        )
        result = await session.execute(stmt)
        affected += int(result.rowcount)  # type: ignore[attr-defined]
    return affected


async def latest_ts(
    session: AsyncSession, instrument_id: int, timeframe: Timeframe
) -> datetime | None:
    """`ts` de la última vela guardada, o `None` si no hay ninguna."""
    stmt = select(func.max(OhlcvBar.ts)).where(
        OhlcvBar.instrument_id == instrument_id, OhlcvBar.timeframe == timeframe.value
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def fetch_latest(
    session: AsyncSession,
    instrument_id: int,
    timeframe: Timeframe,
    limit: int,
    symbol: str,
) -> list[CandleSchema]:
    """Las últimas `limit` velas, en orden ascendente de `ts`."""
    stmt = (
        select(OhlcvBar)
        .where(OhlcvBar.instrument_id == instrument_id, OhlcvBar.timeframe == timeframe.value)
        .order_by(OhlcvBar.ts.desc())
        .limit(limit)
    )
    bars = (await session.execute(stmt)).scalars().all()
    return [
        CandleSchema(
            symbol=symbol,
            timeframe=timeframe,
            ts=bar.ts,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
        )
        for bar in reversed(bars)
    ]
