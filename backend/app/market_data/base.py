"""Contrato común de los proveedores de datos de mercado (D14) y utilidades compartidas."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Protocol

from app.schemas.candle import CandleSchema
from app.schemas.enums import Provider, Timeframe
from app.schemas.instrument import InstrumentSchema


class MarketDataError(Exception):
    """Fallo al obtener o interpretar datos de un proveedor (mensaje en español)."""


class MarketDataAdapter(Protocol):
    """Fuente de velas OHLCV de un proveedor.

    `fetch_ohlcv` devuelve solo velas cerradas (D5), con `ts` = apertura en UTC, en orden
    ascendente, sin duplicados y dentro de `start <= ts < end`. La paginación es interna.
    Un adaptador es de un solo uso: al terminar `fetch_ohlcv` libera sus conexiones.
    """

    provider: Provider

    async def fetch_ohlcv(
        self,
        instrument: InstrumentSchema,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[CandleSchema]: ...


def utcnow() -> datetime:
    """Reloj por defecto de los adaptadores (se inyecta otro en los tests)."""
    return datetime.now(UTC)


def drop_open_candle(
    candles: Sequence[CandleSchema], tf: Timeframe, now: datetime
) -> list[CandleSchema]:
    """Descarta las velas aún abiertas: se conservan las que cumplen `ts + duración <= now` (D5)."""
    duration = tf.duration
    return [c for c in candles if c.ts + duration <= now]
