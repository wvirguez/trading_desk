"""Servicio de stream: fuente de ticks y sondeo periódico."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories import ohlcv as ohlcv_repo
from app.repositories import trade_signals as signals_repo
from app.schemas.enums import Timeframe
from app.schemas.signals import TradeSignalSchema
from app.schemas.stream import (
    SignalAlertEvent,
    StreamErrorEvent,
    StreamEvent,
    TickUpdateEvent,
)
from app.services.backtest import InstrumentNotFoundError


class Clock(Protocol):
    """Reloj inyectable para tests."""

    def now(self) -> datetime: ...


class TickSource(Protocol):
    """Fuente de ticks (Protocol para permitir sustitución: DB, feed real, test)."""

    @abstractmethod
    async def get_latest_tick(self, symbol: str, timeframe: Timeframe) -> TickUpdateEvent: ...


class DbTickSource:
    """Fuente de ticks que lee el último cierre ingerido de la BD (D120)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_latest_tick(self, symbol: str, timeframe: Timeframe) -> TickUpdateEvent:
        from app.repositories import instruments as instruments_repo

        instrument = await instruments_repo.get_by_symbol(self._session, symbol)
        if instrument is None:
            raise InstrumentNotFoundError(symbol)

        candles = await ohlcv_repo.fetch_latest(self._session, instrument.id, timeframe, 1, symbol)
        if not candles:
            raise RuntimeError(f"No hay velas para {symbol} {timeframe.value}")

        latest = candles[-1]
        return TickUpdateEvent(
            type="tick",
            symbol=symbol,
            timeframe=timeframe,
            price=str(latest.close),
            provisional=True,
        )


@dataclass(slots=True)
class StreamPoller:
    """Generador asíncrono que emite eventos de stream periódicamente.

    - Emite un TickUpdateEvent al inicio y solo cuando cambia el precio.
    - Emite SignalAlertEvent solo para señales APPROVED posteriores a `since`,
      una única vez cada una.
    - Un fallo de la fuente emite StreamErrorEvent y el sondeo continúa.
    - Intervalo y reloj inyectables para tests.
    """

    source: TickSource
    symbol: str
    timeframe: Timeframe
    interval: timedelta
    clock: Clock
    since: datetime
    session_factory: async_sessionmaker[AsyncSession]
    list_approved_since: Callable[
        [AsyncSession, str, datetime],
        Awaitable[list[TradeSignalSchema]],
    ] = signals_repo.list_approved_since

    _last_tick_price: str | None = None
    _seen_signal_ids: set[UUID] = field(default_factory=set)

    @asynccontextmanager
    async def _session(self) -> AsyncGenerator[AsyncSession, None]:
        async with self.session_factory() as session:
            yield session

    async def _emit_tick(self) -> TickUpdateEvent | StreamErrorEvent | None:
        try:
            tick = await self.source.get_latest_tick(self.symbol, self.timeframe)
        except Exception as e:
            return StreamErrorEvent(type="error", message=str(e))

        if self._last_tick_price != tick.price:
            self._last_tick_price = tick.price
            return tick
        return None

    async def _emit_signals(self) -> list[SignalAlertEvent]:
        async with self._session() as session:
            signals = await self.list_approved_since(session, self.symbol, self.since)
        new_signals = [s for s in signals if s.id not in self._seen_signal_ids]
        for s in new_signals:
            self._seen_signal_ids.add(s.id)
        return [SignalAlertEvent(type="signal", signal=s) for s in new_signals]

    async def __aiter__(self) -> AsyncGenerator[StreamEvent, None]:
        # Primer tick inmediato
        tick_event = await self._emit_tick()
        if tick_event is not None:
            yield tick_event

        while True:
            self.clock.now()  # Avanza el reloj (en tests se avanza manualmente)
            await self._sleep()

            tick_event = await self._emit_tick()
            if tick_event is not None:
                yield tick_event

            signal_events = await self._emit_signals()
            for se in signal_events:
                yield se

    async def _sleep(self) -> None:
        """Espera el intervalo; en tests el reloj se avanza manualmente."""
        import asyncio

        await asyncio.sleep(self.interval.total_seconds())
