"""Guardas de cartera y veto determinista (D62, D63)."""

import math
from decimal import Decimal
from typing import Any

import pytest

from app.risk import guards
from app.risk.guards import evaluate_trade, risk_reward
from app.schemas.enums import Direction, VetoReason
from app.schemas.risk import OpenPosition, PositionSizeResult, ProposedTrade
from tests.risk._helpers import EURUSD, D, long_trade, make_settings, make_state

S = make_settings()


def _pos(symbol: str, direction: Direction, risk: str) -> OpenPosition:
    return OpenPosition(symbol=symbol, direction=direction, risk_amount=D(risk))


def test_no_veto_approves_with_size() -> None:
    d = evaluate_trade(long_trade(), make_state(), {}, EURUSD, S)
    assert d.approved and d.reasons == [] and d.messages == []
    assert d.size is not None and d.size.units == D(50000)
    assert d.rr == D("1.8")


def test_risk_reward_values() -> None:
    assert risk_reward(long_trade("1.08860")) == D("1.8")
    short = ProposedTrade(
        symbol="EUR/USD",
        direction=Direction.SHORT,
        entry=D("1.0850"),
        stop_loss=D("1.0870"),
        take_profit=D("1.0810"),
    )
    assert risk_reward(short) == D(2)
    assert risk_reward(long_trade("1.0800")) is None


def test_rr_179_vetoed_and_exact_18_passes() -> None:
    d = evaluate_trade(long_trade("1.08858"), make_state(), {}, EURUSD, S)
    assert d.reasons == [VetoReason.RR_BELOW_MIN]
    assert d.messages == ["R:R 1.79 por debajo del mínimo 1.8"]
    assert d.size is not None  # se conserva para trazabilidad
    assert evaluate_trade(long_trade("1.08860"), make_state(), {}, EURUSD, S).approved


def test_daily_loss_exact_limit_vetoes_and_below_passes() -> None:
    d = evaluate_trade(long_trade(), make_state(pnl="-300"), {}, EURUSD, S)
    assert d.reasons == [VetoReason.DAILY_LOSS_LIMIT]
    assert "\u22123.00 %" in d.messages[0] and "3.0 %" in d.messages[0]
    assert evaluate_trade(long_trade(), make_state(pnl="-299"), {}, EURUSD, S).approved


def test_open_risk_limit() -> None:
    state = make_state([_pos("GBP/USD", Direction.SHORT, "250")])  # 2.5 %
    d = evaluate_trade(long_trade(), state, {}, EURUSD, S)
    assert d.reasons == [VetoReason.OPEN_RISK_LIMIT]
    assert d.messages == [
        "Riesgo abierto 3.50 % (existente 2.50 % + nuevo 1.00 %) supera el máximo 3.0 %"
    ]


def test_open_risk_exact_max_passes() -> None:
    state = make_state([_pos("GBP/USD", Direction.SHORT, "200")])  # 2 % + 1 % = 3 %
    assert evaluate_trade(long_trade(), state, {}, EURUSD, S).approved


@pytest.mark.parametrize("rho", [0.9, -0.9, math.nan])
def test_correlated_same_direction_vetoed(rho: float) -> None:
    state = make_state([_pos("GBP/USD", Direction.LONG, "150")])
    d = evaluate_trade(long_trade(), state, {("EUR/USD", "GBP/USD"): rho}, EURUSD, S)
    assert d.reasons == [VetoReason.CORRELATED_RISK_LIMIT]
    assert "2.50 %" in d.messages[0] and "2.0 %" in d.messages[0]


def test_missing_pair_treated_as_one() -> None:
    state = make_state([_pos("GBP/USD", Direction.LONG, "150")])
    d = evaluate_trade(long_trade(), state, {}, EURUSD, S)
    assert d.reasons == [VetoReason.CORRELATED_RISK_LIMIT]


def test_low_correlation_or_opposite_direction_not_counted() -> None:
    low = make_state([_pos("GBP/USD", Direction.LONG, "150")])
    assert evaluate_trade(long_trade(), low, {("EUR/USD", "GBP/USD"): 0.3}, EURUSD, S).approved
    opp = make_state([_pos("GBP/USD", Direction.SHORT, "150")])
    assert evaluate_trade(long_trade(), opp, {("EUR/USD", "GBP/USD"): 0.99}, EURUSD, S).approved


def test_same_symbol_counts_as_rho_one() -> None:
    state = make_state([_pos("EUR/USD", Direction.LONG, "150")])
    d = evaluate_trade(long_trade(), state, {("EUR/USD", "EUR/USD"): 0.0}, EURUSD, S)
    assert d.reasons == [VetoReason.CORRELATED_RISK_LIMIT]


def test_invalid_levels_long_and_short() -> None:
    long_bad = ProposedTrade(
        symbol="EUR/USD",
        direction=Direction.LONG,
        entry=D("1.0850"),
        stop_loss=D("1.0870"),
        take_profit=D("1.0900"),
    )
    short_bad = ProposedTrade(
        symbol="EUR/USD",
        direction=Direction.SHORT,
        entry=D("1.0850"),
        stop_loss=D("1.0830"),
        take_profit=D("1.0800"),
    )
    for trade in (long_bad, short_bad):
        d = evaluate_trade(trade, make_state(), {}, EURUSD, S)
        assert not d.approved
        assert d.reasons == [VetoReason.INVALID_LEVELS]
        assert d.size is None and d.rr is None
        assert "inválidos" in d.messages[0]


def test_size_below_lot() -> None:
    trade = ProposedTrade(
        symbol="EUR/USD",
        direction=Direction.LONG,
        entry=D(100000),
        stop_loss=D(50000),
        take_profit=D(200000),
    )
    d = evaluate_trade(trade, make_state(equity="100", day_start="100"), {}, EURUSD, S)
    assert d.reasons == [VetoReason.SIZE_BELOW_LOT]
    assert d.size is not None and d.size.units == 0
    assert "lote" in d.messages[0]


def test_risk_per_trade_exceeded_defense(monkeypatch: pytest.MonkeyPatch) -> None:
    # position_size nunca excede el riesgo pedido; se simula un cálculo defectuoso.
    real = guards.position_size

    def faulty(*args: Any, **kwargs: Any) -> PositionSizeResult:
        r = real(*args, **kwargs)
        return r.model_copy(update={"risk_pct": D("1.5")})

    monkeypatch.setattr(guards, "position_size", faulty)
    d = evaluate_trade(long_trade(), make_state(), {}, EURUSD, S)
    assert d.reasons == [VetoReason.RISK_PER_TRADE_EXCEEDED]
    assert "1.50 %" in d.messages[0] and "1.0 %" in d.messages[0]


def test_multiple_reasons_accumulate_in_stable_order() -> None:
    state = make_state(
        [_pos("GBP/USD", Direction.LONG, "250")],
        pnl="-300",
    )
    d = evaluate_trade(long_trade("1.08700"), state, {("EUR/USD", "GBP/USD"): 0.95}, EURUSD, S)
    assert d.reasons == [
        VetoReason.RR_BELOW_MIN,
        VetoReason.DAILY_LOSS_LIMIT,
        VetoReason.OPEN_RISK_LIMIT,
        VetoReason.CORRELATED_RISK_LIMIT,
    ]
    assert len(d.messages) == 4
    assert len(set(d.reasons)) == 4


def test_nonpositive_equity_raises() -> None:
    with pytest.raises(ValueError):
        evaluate_trade(long_trade(), make_state(equity="0"), {}, EURUSD, S)


def test_decimal_types() -> None:
    d = evaluate_trade(long_trade(), make_state(), {}, EURUSD, S)
    assert isinstance(d.rr, Decimal)


def test_rr_message_truncates_instead_of_rounding_up() -> None:
    # R:R 1.7999 no debe mostrarse como «1.80 por debajo del mínimo 1.8».
    d = evaluate_trade(long_trade("1.0885998"), make_state(), {}, EURUSD, S)
    assert d.reasons == [VetoReason.RR_BELOW_MIN]
    assert d.messages == ["R:R 1.79 por debajo del mínimo 1.8"]
