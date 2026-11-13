import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.enums import Direction, VetoReason
from app.schemas.risk import (
    GuardDecision,
    KellyResult,
    OpenPosition,
    PortfolioState,
    PositionSizeResult,
    ProposedTrade,
)


def _size() -> PositionSizeResult:
    return PositionSizeResult(
        units=Decimal("1000"),
        risk_amount=Decimal("99.50"),
        risk_pct=Decimal("0.00995"),
        stop_distance=Decimal("0.0995"),
        notional=Decimal("1100.25"),
    )


def test_guard_decision_aprobada_valida() -> None:
    d = GuardDecision(approved=True, reasons=[], messages=[], rr=Decimal("2.0"), size=_size())
    assert d.approved
    assert d.rr == Decimal("2.0")


def test_guard_decision_aprobada_con_motivos_falla() -> None:
    with pytest.raises(ValidationError, match="aprobada"):
        GuardDecision(approved=True, reasons=[VetoReason.RR_BELOW_MIN], messages=["x"])


def test_guard_decision_rechazada_con_motivos() -> None:
    d = GuardDecision(
        approved=False,
        reasons=[VetoReason.RR_BELOW_MIN, VetoReason.INVALID_LEVELS],
        messages=["R:R 1.2 < 1.8", "Stop del lado equivocado"],
    )
    assert d.rr is None
    assert d.size is None
    assert json.loads(d.model_dump_json())["reasons"] == ["RR_BELOW_MIN", "INVALID_LEVELS"]


def test_decimales_viajan_como_cadena_en_json() -> None:
    state = PortfolioState(
        equity=Decimal("10000.00"),
        day_start_equity=Decimal("10050.5"),
        realized_pnl_today=Decimal("-50.50"),
        open_positions=[
            OpenPosition(symbol="BTC/USDT", direction=Direction.LONG, risk_amount=Decimal("100"))
        ],
    )
    data = json.loads(state.model_dump_json())
    assert data["equity"] == "10000.00"
    assert data["realized_pnl_today"] == "-50.50"
    assert data["open_positions"][0]["risk_amount"] == "100"
    trade = ProposedTrade(
        symbol="EUR/USD",
        direction=Direction.SHORT,
        entry=Decimal("1.1000"),
        stop_loss=Decimal("1.1050"),
        take_profit=Decimal("1.0900"),
    )
    assert json.loads(trade.model_dump_json())["take_profit"] == "1.0900"
    assert json.loads(_size().model_dump_json())["units"] == "1000"


def test_kelly_usa_float() -> None:
    k = KellyResult(full_kelly=0.2, fraction=0.05, capped=False)
    assert isinstance(k.fraction, float)


def test_inmutabilidad() -> None:
    d = GuardDecision(approved=False, reasons=[VetoReason.DAILY_LOSS_LIMIT], messages=["x"])
    with pytest.raises(ValidationError):
        d.approved = True  # type: ignore[misc]
    with pytest.raises(ValidationError):
        _size().units = Decimal(1)  # type: ignore[misc]
    pos = OpenPosition(symbol="X", direction=Direction.LONG, risk_amount=Decimal(1))
    with pytest.raises(ValidationError):
        pos.risk_amount = Decimal(2)  # type: ignore[misc]
