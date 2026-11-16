"""Tests `db` del estado de cartera real (D90, D138)."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.repositories import instruments as instruments_repo
from app.repositories import paper_orders as orders_repo
from app.repositories import trade_signals as signals_repo
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
from app.services.portfolio import load_portfolio_state

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("use_test_db")]


def _settings(**kw: object) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg]


NOW = datetime(2026, 3, 10, 15, 0, tzinfo=UTC)  # reloj inyectado


def _make_signal(status: SignalStatus, risk: str) -> TradeSignalSchema:
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
            risk_amount=Decimal(risk),
            risk_pct=Decimal(1),
            stop_distance=Decimal("0.01"),
            notional=Decimal(11),
        ),
        status=status,
        regime=RegimeLabel.TRENDING,
        rationale="prueba",
        veto_reasons=[],
        created_at=datetime.now(UTC),
    )


async def _closed_order(session: AsyncSession, pnl: str, closed_at: datetime) -> None:
    row = await instruments_repo.get_by_symbol(session, "EUR/USD")
    assert row is not None
    signal = await signals_repo.insert_signal(
        session, _make_signal(SignalStatus.EXECUTED, "100"), row.id
    )
    order = await orders_repo.insert_order(session, signal, closed_at - timedelta(hours=2))
    value = Decimal(pnl)
    await orders_repo.update_order_state(
        session,
        order,
        status=OrderStatus.CLOSED_TP if value > 0 else OrderStatus.CLOSED_SL,
        updated_at=closed_at,
        fill_price=Decimal("1.1"),
        filled_at=closed_at - timedelta(hours=1),
        exit_price=Decimal("1.09"),
        closed_at=closed_at,
        realized_pnl=value,
        last_processed_ts=closed_at,
    )


async def test_sin_ordenes_el_equity_es_el_configurado(db_session: AsyncSession) -> None:
    state, warnings = await load_portfolio_state(
        db_session, _settings(account_equity_usd=12345), NOW
    )

    assert state.equity == state.day_start_equity == Decimal(12345)
    assert state.realized_pnl_today == 0
    assert state.open_positions == []
    assert warnings == []


async def test_el_aviso_de_cartera_simulada_ya_no_existe() -> None:
    from app.services import portfolio

    assert not hasattr(portfolio, "SIMULATED_PORTFOLIO_WARNING")


async def test_orden_cerrada_hoy_en_perdida_baja_el_equity(db_session: AsyncSession) -> None:
    await _closed_order(db_session, "-80", NOW - timedelta(hours=3))
    await db_session.commit()

    state, _ = await load_portfolio_state(db_session, _settings(), NOW)

    assert state.realized_pnl_today == Decimal(-80)
    assert state.equity == Decimal(9920)
    assert state.day_start_equity == Decimal(10000) == state.equity - state.realized_pnl_today


async def test_orden_cerrada_ayer_entra_en_equity_pero_no_en_el_dia(
    db_session: AsyncSession,
) -> None:
    yesterday = datetime(2026, 3, 9, 23, 59, tzinfo=UTC)
    await _closed_order(db_session, "-50", yesterday)
    await _closed_order(db_session, "30", datetime(2026, 3, 10, 0, 0, tzinfo=UTC))  # hoy 00:00
    await db_session.commit()

    state, _ = await load_portfolio_state(db_session, _settings(), NOW)

    assert state.equity == Decimal(9980)
    assert state.realized_pnl_today == Decimal(30)
    assert state.day_start_equity == Decimal(9950)


async def test_el_pnl_no_realizado_no_entra_en_equity(db_session: AsyncSession) -> None:
    row = await instruments_repo.get_by_symbol(db_session, "EUR/USD")
    assert row is not None
    signal = await signals_repo.insert_signal(
        db_session, _make_signal(SignalStatus.EXECUTED, "100"), row.id
    )
    order = await orders_repo.insert_order(db_session, signal, NOW - timedelta(hours=2))
    await orders_repo.update_order_state(
        db_session,
        order,
        status=OrderStatus.OPEN,
        updated_at=NOW,
        fill_price=Decimal("1.1"),
        filled_at=NOW - timedelta(hours=1),
        last_processed_ts=NOW - timedelta(hours=1),
    )
    await db_session.commit()

    state, _ = await load_portfolio_state(db_session, _settings(), NOW)

    assert state.equity == state.day_start_equity == Decimal(10000)
    assert state.realized_pnl_today == 0
    assert [p.risk_amount for p in state.open_positions] == [Decimal(100)]


async def test_pending_fill_y_open_aparecen_como_posiciones(db_session: AsyncSession) -> None:
    row = await instruments_repo.get_by_symbol(db_session, "EUR/USD")
    assert row is not None
    for risk in ("100", "60"):
        signal = await signals_repo.insert_signal(
            db_session, _make_signal(SignalStatus.EXECUTED, risk), row.id
        )
        await orders_repo.insert_order(db_session, signal, NOW)
    await db_session.commit()

    state, _ = await load_portfolio_state(db_session, _settings(), NOW)

    assert sorted(p.risk_amount for p in state.open_positions) == [Decimal(60), Decimal(100)]


async def test_las_ordenes_activas_son_posiciones_abiertas(db_session: AsyncSession) -> None:
    row = await instruments_repo.get_by_symbol(db_session, "EUR/USD")
    assert row is not None
    executed = await signals_repo.insert_signal(
        db_session, _make_signal(SignalStatus.EXECUTED, "100"), row.id
    )
    await orders_repo.insert_order(db_session, executed, datetime.now(UTC))
    await signals_repo.insert_signal(db_session, _make_signal(SignalStatus.APPROVED, "50"), row.id)
    await db_session.commit()

    state, _ = await load_portfolio_state(db_session, _settings())

    assert [(p.symbol, p.direction, p.risk_amount) for p in state.open_positions] == [
        ("EUR/USD", Direction.SHORT, Decimal(100))
    ]
