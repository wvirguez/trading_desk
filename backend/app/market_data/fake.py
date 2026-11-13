"""Adaptador determinista para tests de ingesta y endpoint (sin red)."""

import random
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal

from app.market_data.base import drop_open_candle, utcnow
from app.schemas.candle import CandleSchema
from app.schemas.enums import Provider, Timeframe
from app.schemas.instrument import InstrumentSchema

_MIN_TICKS = 1_000
_MAX_TICKS = 2_000
_MAX_WICK_TICKS = 100
_MAX_VOLUME_LOTS = 10_000


class FakeAdapter:
    """Genera velas válidas y alineadas a partir de una semilla.

    Cada vela depende solo de `(seed, símbolo, timeframe, ts)`, de modo que rangos solapados
    devuelven exactamente la misma vela. Devuelve `start <= ts < end` y solo velas cerradas.
    """

    def __init__(
        self,
        seed: int = 0,
        provider: Provider = Provider.BINANCE,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self.seed = seed
        self.provider = provider
        self._now = now

    async def fetch_ohlcv(
        self,
        instrument: InstrumentSchema,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[CandleSchema]:
        step = timeframe.duration
        ts = timeframe.floor(start)
        if ts < start:
            ts += step
        candles: list[CandleSchema] = []
        while ts < end:
            candles.append(self._candle(instrument, timeframe, ts))
            ts += step
        return drop_open_candle(candles, timeframe, self._now())

    def _candle(self, instrument: InstrumentSchema, tf: Timeframe, ts: datetime) -> CandleSchema:
        rnd = random.Random(f"{self.seed}|{instrument.symbol}|{tf.value}|{ts.isoformat()}")  # noqa: S311
        tick, lot = instrument.tick_size, instrument.lot_size
        open_ticks = rnd.randint(_MIN_TICKS, _MAX_TICKS)
        close_ticks = rnd.randint(_MIN_TICKS, _MAX_TICKS)
        high_ticks = max(open_ticks, close_ticks) + rnd.randint(0, _MAX_WICK_TICKS)
        low_ticks = min(open_ticks, close_ticks) - rnd.randint(0, _MAX_WICK_TICKS)
        return CandleSchema(
            symbol=instrument.symbol,
            timeframe=tf,
            ts=ts,
            open=tick * open_ticks,
            high=tick * high_ticks,
            low=tick * low_ticks,
            close=tick * close_ticks,
            volume=lot * Decimal(rnd.randint(0, _MAX_VOLUME_LOTS)),
        )
