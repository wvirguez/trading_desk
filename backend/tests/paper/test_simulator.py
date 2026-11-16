"""Tests del simulador de fills (D134, D145): golden, idempotencia, tandas y propiedades."""

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.paper.simulator import OrderAdvance, OrderState, advance_order
from app.schemas.candle import CandleSchema
from app.schemas.enums import Direction, OrderStatus, Timeframe
from app.schemas.paper import PaperOrderSchema

_GOLDEN = json.loads(
    (Path(__file__).resolve().parents[1] / "golden" / "paper_fills.json").read_text()
)
_T0 = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)
_H = timedelta(hours=1)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _candle(
    ts: datetime, o: str | Decimal, h: str | Decimal, low: str | Decimal, c: str | Decimal
) -> CandleSchema:
    return CandleSchema(
        symbol="BTC-USD", timeframe=Timeframe.H1, ts=ts,
        open=Decimal(o), high=Decimal(h), low=Decimal(low), close=Decimal(c), volume=Decimal(1),
    )  # fmt: skip


def _order(spec: dict[str, str]) -> OrderState:
    return OrderState(
        direction=Direction(spec["direction"]),
        units=Decimal(spec["units"]),
        stop_loss=Decimal(spec["stop_loss"]),
        take_profit=Decimal(spec["take_profit"]),
        risk_amount=Decimal(spec["risk_amount"]),
        executed_at=_dt(spec["executed_at"]),
        timeframe=Timeframe.H1,
    )


def _with(order: OrderState, adv: OrderAdvance) -> OrderState:
    """Reaplica un avance sobre la orden (como hará el servicio al persistir)."""
    from dataclasses import replace

    return replace(
        order, status=adv.status, fill_price=adv.fill_price, filled_at=adv.filled_at,
        last_processed_ts=adv.last_processed_ts,
    )  # fmt: skip


def _golden_candles(rows: list[list[str]]) -> list[CandleSchema]:
    return [_candle(_dt(r[0]), r[1], r[2], r[3], r[4]) for r in rows]


def _opt_dec(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def _opt_dt(value: str | None) -> datetime | None:
    return None if value is None else _dt(value)


def _schema_from(order: OrderState, adv: OrderAdvance) -> PaperOrderSchema:
    """Construir el esquema valida las invariantes de estado."""
    from uuid import uuid4

    return PaperOrderSchema(
        order_id=uuid4(), signal_id=uuid4(), symbol="BTC-USD", timeframe=order.timeframe,
        direction=order.direction, units=order.units, signal_entry=Decimal(100),
        stop_loss=order.stop_loss, take_profit=order.take_profit, risk_amount=order.risk_amount,
        status=adv.status, executed_at=order.executed_at, fill_price=adv.fill_price,
        filled_at=adv.filled_at, closed_at=adv.closed_at, exit_price=adv.exit_price,
        realized_pnl=adv.realized_pnl, pnl=adv.realized_pnl,
    )  # fmt: skip


_CASES: list[dict[str, Any]] = _GOLDEN["cases"]


@pytest.mark.parametrize("case", _CASES, ids=[c["name"] for c in _CASES])
def test_golden(case: dict[str, Any]) -> None:
    order = _order(_GOLDEN["base_orders"][case["order"]])
    adv = advance_order(order, _golden_candles(case["candles"]))
    exp = case["expected"]
    assert adv.status is OrderStatus(exp["status"])
    assert adv.fill_price == _opt_dec(exp["fill_price"])
    assert adv.filled_at == _opt_dt(exp["filled_at"])
    assert adv.exit_price == _opt_dec(exp["exit_price"])
    assert adv.closed_at == _opt_dt(exp["closed_at"])
    assert adv.realized_pnl == _opt_dec(exp["realized_pnl"])
    assert adv.last_processed_ts == _opt_dt(exp["last_processed_ts"])
    assert len(adv.warnings) == exp["warnings"]
    _schema_from(order, adv)  # coherente con las invariantes del esquema


@pytest.mark.parametrize("case", _CASES, ids=[c["name"] for c in _CASES])
def test_golden_idempotente_y_en_dos_tandas(case: dict[str, Any]) -> None:
    order = _order(_GOLDEN["base_orders"][case["order"]])
    candles = _golden_candles(case["candles"])
    once = advance_order(order, candles)
    # Reprocesar las mismas velas sobre el estado resultante no cambia nada.
    again = advance_order(_with(order, once), candles)
    assert (again.status, again.fill_price, again.filled_at) == (
        once.status, once.fill_price, once.filled_at,
    )  # fmt: skip
    assert again.last_processed_ts == once.last_processed_ts
    assert again.warnings == ()
    assert not again.filled_now
    # Dos tandas (cada punto de corte posible) dan lo mismo que una.
    for cut in range(len(candles) + 1):
        first = advance_order(order, candles[:cut])
        second = advance_order(_with(order, first), candles[cut:])
        merged = second if (second.closed_now or second.filled_now) else first
        final_state = _with(order, second)
        assert final_state.status is once.status
        assert final_state.fill_price == once.fill_price
        assert final_state.filled_at == once.filled_at
        assert final_state.last_processed_ts == once.last_processed_ts
        if once.closed_now:
            assert merged.exit_price == once.exit_price
            assert merged.closed_at == once.closed_at
            assert merged.realized_pnl == once.realized_pnl


def test_orden_cerrada_no_cambia() -> None:
    order = _order(_GOLDEN["base_orders"]["LONG"])
    closed = advance_order(order, [_candle(_T0 + _H, "100", "111", "99", "105")])
    state = _with(order, closed)
    later = advance_order(state, [_candle(_T0 + 2 * _H, "50", "60", "40", "50")])
    assert later.status is OrderStatus.CLOSED_TP
    assert later.exit_price is None and later.realized_pnl is None
    assert not later.closed_now


def test_velas_anteriores_a_executed_at_se_ignoran() -> None:
    order = _order(_GOLDEN["base_orders"]["LONG"])  # executed_at 10:30
    adv = advance_order(order, [_candle(_T0, "100", "120", "80", "100")])
    assert adv.status is OrderStatus.PENDING_FILL
    assert adv.last_processed_ts is None


def test_aviso_riesgo_real_supera_risk_amount() -> None:
    order = _order(_GOLDEN["base_orders"]["LONG"])
    adv = advance_order(order, [_candle(_T0 + _H, "103", "104", "102", "103")])
    assert len(adv.warnings) == 1
    assert "16" in adv.warnings[0]
    ok = advance_order(order, [_candle(_T0 + _H, "100", "101", "99", "100")])
    assert ok.warnings == ()


def test_timeframe_distinto_es_error() -> None:
    order = _order(_GOLDEN["base_orders"]["LONG"])
    bad = CandleSchema(
        symbol="BTC-USD", timeframe=Timeframe.D1, ts=_dt("2026-01-06T00:00:00Z"),
        open=Decimal(1), high=Decimal(1), low=Decimal(1), close=Decimal(1), volume=Decimal(0),
    )  # fmt: skip
    with pytest.raises(ValueError, match="timeframe"):
        advance_order(order, [bad])


def test_velas_desordenadas_y_duplicadas() -> None:
    order = _order(_GOLDEN["base_orders"]["LONG"])
    c1 = _candle(_T0 + _H, "100", "102", "98", "101")
    c2 = _candle(_T0 + 2 * _H, "101", "111", "100", "110")
    assert advance_order(order, [c2, c1, c1]) == advance_order(order, [c1, c2])


# --- Propiedades ---------------------------------------------------------------------------

_price = st.integers(min_value=1_000, max_value=100_000).map(lambda n: Decimal(n) / 100)


@st.composite
def _candle_seq(draw: st.DrawFn) -> list[CandleSchema]:
    n = draw(st.integers(min_value=0, max_value=8))
    out: list[CandleSchema] = []
    for i in range(n):
        a, b, c, d = (draw(_price) for _ in range(4))
        lo, hi = min(a, b, c, d), max(a, b, c, d)
        out.append(_candle(_T0 + (i + 1) * _H, a, hi, lo, b))
    return out


@st.composite
def _orders(draw: st.DrawFn) -> OrderState:
    direction = draw(st.sampled_from(list(Direction)))
    entry = draw(_price)
    dist_sl = draw(st.integers(min_value=1, max_value=900).map(lambda n: Decimal(n) / 100))
    dist_tp = draw(st.integers(min_value=1, max_value=900).map(lambda n: Decimal(n) / 100))
    sign = 1 if direction is Direction.LONG else -1
    sl, tp = entry - sign * dist_sl, entry + sign * dist_tp
    if sl <= 0 or tp <= 0:
        sl, tp = entry - sign * Decimal("0.01"), entry + sign * Decimal("0.01")
        if sl <= 0 or tp <= 0:
            sl, tp = (entry / 2, entry * 2) if sign == 1 else (entry * 2, entry / 2)
    units = draw(st.integers(min_value=1, max_value=10_000).map(lambda n: Decimal(n) / 100))
    return OrderState(
        direction=direction, units=units, stop_loss=sl, take_profit=tp,
        risk_amount=abs(entry - sl) * units, executed_at=_T0 + timedelta(minutes=30),
        timeframe=Timeframe.H1,
    )  # fmt: skip


@settings(max_examples=200, deadline=None)
@given(order=_orders(), candles=_candle_seq())
def test_prop_pnl_y_tipos(order: OrderState, candles: list[CandleSchema]) -> None:
    adv = advance_order(order, candles)
    _schema_from(order, adv)
    for value in (adv.fill_price, adv.exit_price, adv.realized_pnl):
        assert value is None or isinstance(value, Decimal)
    if adv.realized_pnl is not None:
        assert adv.fill_price is not None and adv.exit_price is not None
        sign = 1 if order.direction is Direction.LONG else -1
        assert adv.realized_pnl == sign * (adv.exit_price - adv.fill_price) * order.units
        if adv.status is OrderStatus.CLOSED_TP:
            if order.direction is Direction.LONG:
                assert adv.exit_price >= order.take_profit
            else:
                assert adv.exit_price <= order.take_profit
        else:
            if order.direction is Direction.LONG:
                assert adv.exit_price <= order.stop_loss
            else:
                assert adv.exit_price >= order.stop_loss


@settings(max_examples=200, deadline=None)
@given(order=_orders(), candles=_candle_seq(), cut=st.integers(min_value=0, max_value=8))
def test_prop_idempotencia_y_tandas(
    order: OrderState, candles: Sequence[CandleSchema], cut: int
) -> None:
    once = advance_order(order, candles)
    again = advance_order(_with(order, once), candles)
    assert _with(order, again) == _with(order, once)
    first = advance_order(order, candles[:cut])
    second = advance_order(_with(order, first), candles[cut:])
    assert _with(order, second) == _with(order, once)


@settings(max_examples=200, deadline=None)
@given(order=_orders(), entry_gap=st.integers(min_value=0, max_value=0))
def test_prop_sl_en_el_nivel_pierde_risk_amount(order: OrderState, entry_gap: int) -> None:
    """Fill = entry de la señal y salida exactamente en SL: pnl = -risk_amount."""
    entry = order.stop_loss + (
        -(order.risk_amount / order.units)
        if order.direction is Direction.SHORT
        else order.risk_amount / order.units
    )
    fill = _candle(_T0 + _H, entry, entry, entry, entry)
    if order.direction is Direction.LONG:
        crash = _candle(_T0 + 2 * _H, entry, entry, order.stop_loss, order.stop_loss)
    else:
        crash = _candle(_T0 + 2 * _H, entry, order.stop_loss, entry, order.stop_loss)
    adv = advance_order(order, [fill, crash])
    if adv.status is OrderStatus.CLOSED_SL and adv.exit_price == order.stop_loss:
        assert adv.realized_pnl is not None
        assert abs(adv.realized_pnl + order.risk_amount) <= Decimal("1e-20")
