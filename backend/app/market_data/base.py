"""Contrato común de los proveedores de datos de mercado (D14) y utilidades compartidas."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from app.schemas.candle import CandleSchema
from app.schemas.enums import Provider, Timeframe
from app.schemas.instrument import InstrumentSchema


class MarketDataError(Exception):
    """Fallo al obtener o interpretar datos de un proveedor (mensaje en español)."""


class UnsupportedTimeframeError(MarketDataError):
    """El proveedor no puede entregar ese timeframe para ese instrumento (D48).

    No es un fallo transitorio: la CLI la omite con un aviso en `--all` y la trata como
    error si la combinación se pidió de forma explícita.
    """


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


class NoticeLike(Protocol):
    """Aviso del adaptador: `message` es el texto listo para la CLI (en español)."""

    @property
    def message(self) -> str: ...


@runtime_checkable
class NoticeReporter(Protocol):
    """Adaptador que anota avisos de la última llamada (historia recortada D30, bloques 4h
    parciales D49). `notices` se reinicia en cada `fetch_ohlcv`; vacío = nada que avisar.
    Los demás adaptadores no lo tienen: el servicio lo detecta con `isinstance`.
    """

    @property
    def notices(self) -> Sequence[NoticeLike]: ...


def utcnow() -> datetime:
    """Reloj por defecto de los adaptadores (se inyecta otro en los tests)."""
    return datetime.now(UTC)


def drop_open_candle(
    candles: Sequence[CandleSchema], tf: Timeframe, now: datetime
) -> list[CandleSchema]:
    """Descarta las velas aún abiertas: se conservan las que cumplen `ts + duración <= now` (D5)."""
    duration = tf.duration
    return [c for c in candles if c.ts + duration <= now]
