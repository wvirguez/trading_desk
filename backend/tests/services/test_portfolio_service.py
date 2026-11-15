"""Tests `db` del estado de cartera simulado (D90)."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.repositories import instruments as instruments_repo
from app.repositories import trade_signals as signals_repo
from app.schemas.enums import AssetClass, Direction, RegimeLabel, SignalStatus, Timeframe
from app.schemas.risk import PositionSizeResult
from app.schemas.signals import TradeSignalSchema
from app.services.portfolio import SIMULATED_PORTFOLIO_WARNING, load_portfolio_state

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("use_test_db")]


def _settings(**kw: object) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg]


async def test_estado_simulado_sin_posiciones(db_session: AsyncSession) -> None:
    state, warnings = await load_portfolio_state(db_session, _settings(account_equity_usd=12345))

    assert state.equity == state.day_start_equity == Decimal(12345)
    assert state.realized_pnl_today == 0
    assert state.open_positions == []
    assert warnings == ["Estado de cartera simulado: sin PnL real hasta el paper trading"]
    assert warnings == [SIMULATED_PORTFOLIO_WARNING]


async def test_las_senales_executed_son_posiciones_abiertas(db_session: AsyncSession) -> None:
    row = await instruments_repo.get_by_symbol(db_session, "EUR/USD")
    assert row is not None

    def signal(status: SignalStatus, risk: str) -> TradeSignalSchema:
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

    await signals_repo.insert_signal(db_session, signal(SignalStatus.EXECUTED, "100"), row.id)
    await signals_repo.insert_signal(db_session, signal(SignalStatus.APPROVED, "50"), row.id)
    await db_session.commit()

    state, _ = await load_portfolio_state(db_session, _settings())

    assert [(p.symbol, p.direction, p.risk_amount) for p in state.open_positions] == [
        ("EUR/USD", Direction.SHORT, Decimal(100))
    ]
