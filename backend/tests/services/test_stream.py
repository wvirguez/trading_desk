"""Tests del servicio de stream (sin base de datos)."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.schemas.enums import Timeframe
from app.schemas.stream import (
    SignalAlertEvent,
    StreamErrorEvent,
    TickUpdateEvent,
)
from app.services.stream import DbTickSource, StreamPoller, TickSource


class FakeClock:
    """Reloj falso para tests: avanza manualmente."""

    def __init__(self, start: datetime | None = None):
        self._now = start or datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta


class MockSession:
    """Mock session para tests."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def mock_session_factory() -> async_sessionmaker:
    """Factory que devuelve un async_sessionmaker que produce MockSession."""

    @asynccontextmanager
    async def _factory():
        yield MockSession()

    return async_sessionmaker(_factory, class_=AsyncMock)


class FakeTickSource(TickSource):
    """Fuente de ticks falsa para tests."""

    def __init__(self):
        self._tick: TickUpdateEvent | None = None
        self._should_fail = False
        self._fail_message = "Error simulado"

    def set_tick(self, tick: TickUpdateEvent) -> None:
        self._tick = tick

    def set_failure(self, message: str) -> None:
        self._should_fail = True
        self._fail_message = message

    def clear_failure(self) -> None:
        self._should_fail = False

    async def get_latest_tick(self, symbol: str, timeframe: Timeframe) -> TickUpdateEvent:
        if self._should_fail:
            raise RuntimeError(self._fail_message)
        if self._tick is None:
            raise RuntimeError("No hay tick configurado")
        return self._tick


class TestTickSourceProtocol:
    """Verifica que TickSource es un Protocol."""

    def test_es_protocol(self) -> None:
        assert hasattr(TickSource, "__protocol_attrs__")


class TestDbTickSource:
    """Tests de DbTickSource (requiere base de datos)."""

    @pytest.mark.db
    async def test_obtiene_ultimo_cierre_ingerido(self, db_session, use_test_db) -> None:
        from app.repositories import instruments as instruments_repo
        from app.repositories import ohlcv as ohlcv_repo
        from app.schemas.candle import CandleSchema

        row = await instruments_repo.get_by_symbol(db_session, "BTC/USDT")
        assert row is not None

        candles = [
            CandleSchema(
                symbol="BTC/USDT",
                timeframe=Timeframe.H1,
                ts=datetime(2026, 1, 1, hour=i, tzinfo=UTC),
                open=Decimal("60000"),
                high=Decimal("61000"),
                low=Decimal("59000"),
                close=Decimal(str(60000 + i * 100)),
                volume=Decimal("1.0"),
            )
            for i in range(3)
        ]
        await ohlcv_repo.upsert_candles(db_session, row.id, candles)
        await db_session.commit()

        source = DbTickSource(db_session)
        tick = await source.get_latest_tick("BTC/USDT", Timeframe.H1)

        assert isinstance(tick, TickUpdateEvent)
        assert tick.symbol == "BTC/USDT"
        assert tick.timeframe == Timeframe.H1
        assert tick.price.startswith("60200")
        assert tick.provisional is True

    @pytest.mark.db
    async def test_simbolo_desconocido(self, db_session, use_test_db) -> None:
        from app.services.backtest import InstrumentNotFoundError

        source = DbTickSource(db_session)
        with pytest.raises(InstrumentNotFoundError, match="Instrumento desconocido"):
            await source.get_latest_tick("XYZ", Timeframe.H1)

    @pytest.mark.db
    async def test_sin_velas(self, db_session, use_test_db) -> None:
        from app.repositories import instruments as instruments_repo

        row = await instruments_repo.get_by_symbol(db_session, "EUR/USD")
        assert row is not None

        source = DbTickSource(db_session)
        with pytest.raises(RuntimeError, match="No hay velas para"):
            await source.get_latest_tick("EUR/USD", Timeframe.H1)


class TestStreamPoller:
    """Tests del generador asíncrono StreamPoller."""

    async def test_emite_tick_al_inicio(self) -> None:
        clock = FakeClock()
        source = FakeTickSource()
        source.set_tick(
            TickUpdateEvent(
                type="tick",
                symbol="BTC/USDT",
                timeframe=Timeframe.H1,
                price="60000",
                provisional=True,
            )
        )

        poller = StreamPoller(
            source=source,
            symbol="BTC/USDT",
            timeframe=Timeframe.H1,
            interval=timedelta(seconds=1),
            clock=clock,
            since=datetime(2026, 1, 1, tzinfo=UTC),
            session_factory=mock_session_factory(),
        )

        events = []
        async for event in poller:
            events.append(event)
            if len(events) >= 1:
                break

        assert len(events) == 1
        assert isinstance(events[0], TickUpdateEvent)
        assert events[0].price == "60000"

    async def test_no_duplica_eventos_identicos(self) -> None:
        clock = FakeClock()
        source = FakeTickSource()
        source.set_tick(
            TickUpdateEvent(
                type="tick",
                symbol="BTC/USDT",
                timeframe=Timeframe.H1,
                price="60000",
                provisional=True,
            )
        )

        poller = StreamPoller(
            source=source,
            symbol="BTC/USDT",
            timeframe=Timeframe.H1,
            interval=timedelta(seconds=1),
            clock=clock,
            since=datetime(2026, 1, 1, tzinfo=UTC),
            session_factory=mock_session_factory(),
        )

        events = []
        async for event in poller:
            events.append(event)
            if len(events) >= 1:
                break

        assert len(events) == 1

    async def test_emite_cuando_cambia_precio(self) -> None:
        clock = FakeClock()
        source = FakeTickSource()
        source.set_tick(
            TickUpdateEvent(
                type="tick",
                symbol="BTC/USDT",
                timeframe=Timeframe.H1,
                price="60000",
                provisional=True,
            )
        )

        poller = StreamPoller(
            source=source,
            symbol="BTC/USDT",
            timeframe=Timeframe.H1,
            interval=timedelta(seconds=1),
            clock=clock,
            since=datetime(2026, 1, 1, tzinfo=UTC),
            session_factory=mock_session_factory(),
        )

        events = []
        async for event in poller:
            events.append(event)
            if len(events) >= 2:
                break
            if len(events) == 1:
                source.set_tick(
                    TickUpdateEvent(
                        type="tick",
                        symbol="BTC/USDT",
                        timeframe=Timeframe.H1,
                        price="60100",
                        provisional=True,
                    )
                )
                clock.advance(timedelta(seconds=1))

        assert len(events) == 2
        assert events[0].price == "60000"
        assert events[1].price == "60100"

    async def test_emite_signal_alert_solo_aprobadas_posteriores_a_conexion(self) -> None:
        clock = FakeClock()
        source = FakeTickSource()
        source.set_tick(
            TickUpdateEvent(
                type="tick",
                symbol="BTC/USDT",
                timeframe=Timeframe.H1,
                price="60000",
                provisional=True,
            )
        )

        since = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        clock._now = since

        from uuid import uuid4

        from app.schemas.enums import AssetClass, Direction, RegimeLabel, SignalStatus
        from app.schemas.risk import PositionSizeResult
        from app.schemas.signals import TradeSignalSchema

        signal1 = TradeSignalSchema(
            id=uuid4(),
            analysis_id=uuid4(),
            symbol="BTC/USDT",
            asset_class=AssetClass.CRYPTO,
            timeframe=Timeframe.H1,
            direction=Direction.LONG,
            entry=Decimal("60000"),
            stop_loss=Decimal("59800"),
            take_profit=Decimal("60400"),
            rr=Decimal("2.0"),
            size=PositionSizeResult(
                units=Decimal("0.5"),
                risk_amount=Decimal("100"),
                risk_pct=Decimal("0.01"),
                stop_distance=Decimal("200"),
                notional=Decimal("30000"),
            ),
            status=SignalStatus.APPROVED,
            regime=RegimeLabel.TRENDING,
            rationale="ok",
            veto_reasons=[],
            created_at=since + timedelta(hours=1),
        )

        async def mock_list_approved_since(session, symbol, since_dt):
            if since_dt == since:
                return [signal1]
            return []

        poller = StreamPoller(
            source=source,
            symbol="BTC/USDT",
            timeframe=Timeframe.H1,
            interval=timedelta(seconds=1),
            clock=clock,
            since=since,
            session_factory=mock_session_factory(),
            list_approved_since=mock_list_approved_since,
        )

        events = []
        async for event in poller:
            events.append(event)
            if len(events) >= 2:
                break
            clock.advance(timedelta(seconds=1))

        tick_events = [e for e in events if isinstance(e, TickUpdateEvent)]
        signal_events = [e for e in events if isinstance(e, SignalAlertEvent)]

        assert len(tick_events) == 1
        assert len(signal_events) == 1
        assert signal_events[0].signal.id == signal1.id
        assert signal_events[0].signal.created_at > since

    async def test_signal_alert_una_unica_vez_cada_una(self) -> None:
        clock = FakeClock()
        source = FakeTickSource()
        source.set_tick(
            TickUpdateEvent(
                type="tick",
                symbol="BTC/USDT",
                timeframe=Timeframe.H1,
                price="60000",
                provisional=True,
            )
        )

        since = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        clock._now = since

        from uuid import uuid4

        from app.schemas.enums import AssetClass, Direction, RegimeLabel, SignalStatus
        from app.schemas.risk import PositionSizeResult
        from app.schemas.signals import TradeSignalSchema

        signal = TradeSignalSchema(
            id=uuid4(),
            analysis_id=uuid4(),
            symbol="BTC/USDT",
            asset_class=AssetClass.CRYPTO,
            timeframe=Timeframe.H1,
            direction=Direction.LONG,
            entry=Decimal("60000"),
            stop_loss=Decimal("59800"),
            take_profit=Decimal("60400"),
            rr=Decimal("2.0"),
            size=PositionSizeResult(
                units=Decimal("0.5"),
                risk_amount=Decimal("100"),
                risk_pct=Decimal("0.01"),
                stop_distance=Decimal("200"),
                notional=Decimal("30000"),
            ),
            status=SignalStatus.APPROVED,
            regime=RegimeLabel.TRENDING,
            rationale="ok",
            veto_reasons=[],
            created_at=since + timedelta(hours=1),
        )

        call_count = 0

        async def mock_list_approved_since(session, symbol, since_dt):
            nonlocal call_count
            call_count += 1
            return [signal]

        poller = StreamPoller(
            source=source,
            symbol="BTC/USDT",
            timeframe=Timeframe.H1,
            interval=timedelta(seconds=1),
            clock=clock,
            since=since,
            session_factory=mock_session_factory(),
            list_approved_since=mock_list_approved_since,
        )

        events = []
        async for event in poller:
            events.append(event)
            if len(events) >= 2:  # tick + signal
                break
            clock.advance(timedelta(seconds=1))

        signal_events = [e for e in events if isinstance(e, SignalAlertEvent)]
        assert len(signal_events) == 1

    async def test_error_de_fuente_emite_stream_error_y_continua(self) -> None:
        clock = FakeClock()
        source = FakeTickSource()
        source.set_tick(
            TickUpdateEvent(
                type="tick",
                symbol="BTC/USDT",
                timeframe=Timeframe.H1,
                price="60000",
                provisional=True,
            )
        )

        async def mock_list_approved_since(session, symbol, since_dt):
            return []

        poller = StreamPoller(
            source=source,
            symbol="BTC/USDT",
            timeframe=Timeframe.H1,
            interval=timedelta(seconds=1),
            clock=clock,
            since=datetime(2026, 1, 1, tzinfo=UTC),
            session_factory=mock_session_factory(),
            list_approved_since=mock_list_approved_since,
        )

        events = []
        async for event in poller:
            events.append(event)
            if len(events) >= 3:
                break
            if len(events) == 1:
                source.set_failure("Error de conexión a la base de datos")
                clock.advance(timedelta(seconds=1))
            elif len(events) == 2:
                source.clear_failure()
                source.set_tick(
                    TickUpdateEvent(
                        type="tick",
                        symbol="BTC/USDT",
                        timeframe=Timeframe.H1,
                        price="60100",
                        provisional=True,
                    )
                )
                clock.advance(timedelta(seconds=1))

        tick_events = [e for e in events if isinstance(e, TickUpdateEvent)]
        error_events = [e for e in events if isinstance(e, StreamErrorEvent)]

        assert len(tick_events) == 2
        assert tick_events[0].price == "60000"
        assert tick_events[1].price == "60100"
        assert len(error_events) == 1
        assert "Error de conexión" in error_events[0].message

    async def test_precio_nunca_es_float(self) -> None:
        clock = FakeClock()
        source = FakeTickSource()
        source.set_tick(
            TickUpdateEvent(
                type="tick",
                symbol="BTC/USDT",
                timeframe=Timeframe.H1,
                price="60000.50",
                provisional=True,
            )
        )

        poller = StreamPoller(
            source=source,
            symbol="BTC/USDT",
            timeframe=Timeframe.H1,
            interval=timedelta(seconds=1),
            clock=clock,
            since=datetime(2026, 1, 1, tzinfo=UTC),
            session_factory=mock_session_factory(),
        )

        events = []
        async for event in poller:
            events.append(event)
            if len(events) >= 1:
                break

        tick = events[0]
        assert isinstance(tick.price, str)
        assert not isinstance(tick.price, float)
        assert tick.price == "60000.50"

    async def test_intervalo_y_reloj_inyectables(self) -> None:
        clock = FakeClock()
        source = FakeTickSource()
        source.set_tick(
            TickUpdateEvent(
                type="tick",
                symbol="BTC/USDT",
                timeframe=Timeframe.H1,
                price="60000",
                provisional=True,
            )
        )

        custom_interval = timedelta(seconds=5)
        poller = StreamPoller(
            source=source,
            symbol="BTC/USDT",
            timeframe=Timeframe.H1,
            interval=custom_interval,
            clock=clock,
            since=datetime(2026, 1, 1, tzinfo=UTC),
            session_factory=mock_session_factory(),
        )

        assert poller.interval == custom_interval
        assert poller.clock is clock
