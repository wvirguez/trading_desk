"""Tests `db` de `refresh_orders` (D135): avance de órdenes con velas ingeridas."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import instruments as instruments_repo
from app.repositories import ohlcv as ohlcv_repo
from app.repositories import paper_orders as orders_repo
from app.repositories import trade_signals as signals_repo
from app.schemas.candle import CandleSchema
from app.schemas.enums import (
    AssetClass,
    Direction,
    OrderStatus,
    RegimeLabel,
    SignalStatus,
    Timeframe,
)
from app.schemas.risk import PositionSizeResult
from app.schemas.signals import TradeSignalSchema
from app.services.paper import refresh_orders

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("use_test_db")]

T0 = datetime(2026, 3, 10, 10, 0, tzinfo=UTC)
H = timedelta(hours=1)


def _signal() -> TradeSignalSchema:
    return TradeSignalSchema(
        id=uuid.uuid4(),
        analysis_id=uuid.uuid4(),
        symbol="EUR/USD",
        asset_class=AssetClass.FX,
        timeframe=Timeframe.H1,
        direction=Direction.SHORT,
        entry=Decimal("1.1"),
        stop_loss=Decimal("1.11"),
        take_profit=Decimal("1.08"),
        rr=Decimal(2),
        size=PositionSizeResult(
            units=Decimal(10),
            risk_amount=Decimal(100),
            risk_pct=Decimal(1),
            stop_distance=Decimal("0.01"),
            notional=Decimal(11),
        ),
        status=SignalStatus.EXECUTED,
        regime=RegimeLabel.TRENDING,
        rationale="prueba",
        veto_reasons=[],
        created_at=T0,
    )


def _candle(ts: datetime, o: str, h: str, low: str, c: str) -> CandleSchema:
    return CandleSchema(
        symbol="EUR/USD", timeframe=Timeframe.H1, ts=ts,
        open=Decimal(o), high=Decimal(h), low=Decimal(low), close=Decimal(c), volume=Decimal(1),
    )  # fmt: skip


async def _new_order(session: AsyncSession) -> tuple[int, uuid.UUID]:
    row = await instruments_repo.get_by_symbol(session, "EUR/USD")
    assert row is not None
    signal = await signals_repo.insert_signal(session, _signal(), row.id)
    order = await orders_repo.insert_order(session, signal, T0)
    await session.commit()
    return row.id, order.id


async def test_sin_velas_posteriores_no_cambia_nada(db_session: AsyncSession) -> None:
    instrument_id, _ = await _new_order(db_session)
    await ohlcv_repo.upsert_candles(
        db_session, instrument_id, [_candle(T0 - H, "1.1", "1.2", "1.0", "1.1")]
    )
    await db_session.commit()

    result = await refresh_orders(db_session, T0)

    assert (result.orders_checked, result.orders_filled, result.orders_closed) == (1, 0, 0)
    [(order, _)] = await orders_repo.list_open_orders(db_session)
    assert order.status == OrderStatus.PENDING_FILL.value and order.last_processed_ts is None


async def test_sin_ordenes_abiertas_devuelve_ceros(db_session: AsyncSession) -> None:
    result = await refresh_orders(db_session)

    assert (result.orders_checked, result.orders_filled, result.orders_closed) == (0, 0, 0)


async def test_pending_fill_pasa_a_open_y_es_idempotente(db_session: AsyncSession) -> None:
    instrument_id, _ = await _new_order(db_session)
    await ohlcv_repo.upsert_candles(
        db_session, instrument_id, [_candle(T0, "1.1", "1.102", "1.099", "1.1")]
    )
    await db_session.commit()

    first = await refresh_orders(db_session, T0 + H)
    second = await refresh_orders(db_session, T0 + 2 * H)

    assert (first.orders_filled, first.orders_closed) == (1, 0)
    assert (second.orders_checked, second.orders_filled, second.orders_closed) == (1, 0, 0)
    [(order, _)] = await orders_repo.list_open_orders(db_session)
    assert order.status == OrderStatus.OPEN.value
    assert order.fill_price == Decimal("1.1") and order.filled_at == T0
    assert order.last_processed_ts == T0


async def test_orden_con_velas_posteriores_llega_a_cerrada(db_session: AsyncSession) -> None:
    instrument_id, _ = await _new_order(db_session)
    await ohlcv_repo.upsert_candles(
        db_session,
        instrument_id,
        [
            _candle(T0, "1.1", "1.102", "1.099", "1.1"),
            _candle(T0 + H, "1.1", "1.101", "1.079", "1.08"),  # toca el TP (SHORT)
        ],
    )
    await db_session.commit()

    first = await refresh_orders(db_session, T0 + 3 * H)
    second = await refresh_orders(db_session, T0 + 4 * H)

    assert (first.orders_checked, first.orders_filled, first.orders_closed) == (1, 1, 1)
    assert (second.orders_checked, second.orders_filled, second.orders_closed) == (0, 0, 0)
    assert await orders_repo.list_open_orders(db_session) == []
    assert await orders_repo.sum_realized_pnl(db_session) == Decimal("0.2")


async def test_el_avance_es_incremental_entre_llamadas(db_session: AsyncSession) -> None:
    instrument_id, _ = await _new_order(db_session)
    await ohlcv_repo.upsert_candles(
        db_session, instrument_id, [_candle(T0, "1.1", "1.102", "1.099", "1.1")]
    )
    await db_session.commit()
    await refresh_orders(db_session, T0 + H)

    await ohlcv_repo.upsert_candles(
        db_session,
        instrument_id,
        [_candle(T0 + H, "1.1", "1.12", "1.09", "1.11")],  # toca el SL
    )
    await db_session.commit()
    result = await refresh_orders(db_session, T0 + 2 * H)

    assert (result.orders_filled, result.orders_closed) == (0, 1)
    assert await orders_repo.sum_realized_pnl(db_session) == Decimal("-0.1")
