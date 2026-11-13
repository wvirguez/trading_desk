"""Adaptador de ccxt (Binance, datos públicos). Es el único módulo que toca ccxt."""

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

import ccxt
import ccxt.async_support as ccxt_async
from pydantic import ValidationError

from app.market_data.base import MarketDataError, drop_open_candle, utcnow
from app.schemas.candle import CandleSchema
from app.schemas.enums import Provider, Timeframe
from app.schemas.instrument import InstrumentSchema

PAGE_LIMIT = 1000


class CcxtExchange(Protocol):
    """Subconjunto de la API asíncrona de ccxt que usa el adaptador."""

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: int | None = None,
        limit: int | None = None,
    ) -> list[list[float]]: ...

    async def close(self) -> None: ...


def build_binance_exchange() -> CcxtExchange:
    """Exchange de producción: Binance, solo datos públicos, con límite de tasa activo."""
    exchange: CcxtExchange = ccxt_async.binance({"enableRateLimit": True})
    return exchange


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


class CcxtAdapter:
    """Velas OHLCV vía ccxt. Un adaptador es de un solo uso: cierra el exchange al terminar."""

    provider = Provider.BINANCE

    def __init__(self, exchange: CcxtExchange, now: Callable[[], datetime] = utcnow) -> None:
        self._exchange = exchange
        self._now = now

    async def fetch_ohlcv(
        self,
        instrument: InstrumentSchema,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[CandleSchema]:
        if instrument.provider is not Provider.BINANCE:
            raise MarketDataError(
                f"El instrumento {instrument.symbol} es de {instrument.provider.value}, "
                "no de BINANCE"
            )
        try:
            candles = await self._paginate(instrument, timeframe, start, end)
        except MarketDataError:
            raise
        except ccxt.BaseError as exc:
            raise MarketDataError(f"Error de Binance (ccxt): {exc}") from exc
        except Exception as exc:
            raise MarketDataError(f"Fallo al consultar Binance: {type(exc).__name__}") from exc
        finally:
            await self._exchange.close()
        return drop_open_candle(candles, timeframe, self._now())

    async def _paginate(
        self,
        instrument: InstrumentSchema,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[CandleSchema]:
        step_ms = int(timeframe.duration.total_seconds() * 1000)
        start_ms, end_ms = _ms(start), _ms(end)
        since = _ms(timeframe.floor(start))
        by_ts: dict[int, CandleSchema] = {}
        while since < end_ms:
            rows = await self._exchange.fetch_ohlcv(
                instrument.provider_symbol, timeframe.value, since=since, limit=PAGE_LIMIT
            )
            if not rows:
                break
            last_ms = since
            for row in rows:
                ts_ms = int(row[0])
                last_ms = max(last_ms, ts_ms)
                if start_ms <= ts_ms < end_ms:
                    by_ts[ts_ms] = self._to_candle(instrument, timeframe, row)
            since = last_ms + step_ms
        return [by_ts[k] for k in sorted(by_ts)]

    @staticmethod
    def _to_candle(
        instrument: InstrumentSchema, timeframe: Timeframe, row: list[float]
    ) -> CandleSchema:
        try:
            return CandleSchema(
                symbol=instrument.symbol,
                timeframe=timeframe,
                ts=datetime.fromtimestamp(int(row[0]) / 1000, tz=UTC),
                open=Decimal(str(row[1])),  # D4: nunca Decimal(float)
                high=Decimal(str(row[2])),
                low=Decimal(str(row[3])),
                close=Decimal(str(row[4])),
                volume=Decimal(str(row[5])),
            )
        except (ValidationError, IndexError, ArithmeticError) as exc:
            raise MarketDataError(f"Vela inválida de Binance: {exc}") from exc
