"""Propiedades del position sizing (D60)."""

from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from app.risk.sizing import position_size
from app.schemas.enums import AssetClass, Provider, SessionType
from app.schemas.instrument import InstrumentSchema

ticks = st.sampled_from([Decimal("0.00001"), Decimal("0.01"), Decimal("0.001")])
lots = st.sampled_from([Decimal("1"), Decimal("0.00001"), Decimal("0.001")])
equities = st.decimals(Decimal("1"), Decimal("10000000"), places=2)
risks = st.decimals(Decimal("0.01"), Decimal("1"), places=2)
prices = st.decimals(Decimal("0.0001"), Decimal("100000"), places=5)


def _inst(tick: Decimal, lot: Decimal) -> InstrumentSchema:
    return InstrumentSchema(
        symbol="X/USD",
        asset_class=AssetClass.FX,
        provider=Provider.YAHOO,
        provider_symbol="X",
        base_currency="X",
        quote_currency="USD",
        tick_size=tick,
        lot_size=lot,
        session=SessionType.FX_24_5,
    )


@settings(derandomize=True, max_examples=200, deadline=None)
@given(equities, risks, prices, prices, ticks, lots)
def test_propiedades(
    equity: Decimal, risk: Decimal, entry: Decimal, stop: Decimal, tick: Decimal, lot: Decimal
) -> None:
    if entry == stop:
        return
    r = position_size(equity, risk, entry, stop, _inst(tick, lot))
    assert r.risk_amount <= equity * risk / 100
    assert r.risk_pct <= risk
    assert r.units >= 0
    assert r.units % lot == 0
    assert r.stop_distance % tick == 0
    assert r.stop_distance >= abs(entry - stop)


@settings(derandomize=True, max_examples=200, deadline=None)
@given(equities, risks, prices, prices, prices, ticks, lots)
def test_mas_distancia_no_da_mas_unidades(
    equity: Decimal,
    risk: Decimal,
    entry: Decimal,
    s1: Decimal,
    s2: Decimal,
    tick: Decimal,
    lot: Decimal,
) -> None:
    if entry == s1 or entry == s2:
        return
    inst = _inst(tick, lot)
    a = position_size(equity, risk, entry, s1, inst)
    b = position_size(equity, risk, entry, s2, inst)
    if abs(entry - s1) <= abs(entry - s2):
        assert a.units >= b.units
    else:
        assert b.units >= a.units
