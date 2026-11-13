"""Propiedades de las guardas: criterio de éxito de la misión (ninguna aprobación viola límites)."""

from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from app.risk.guards import evaluate_trade, risk_reward
from app.schemas.enums import Direction
from app.schemas.risk import OpenPosition, PortfolioState, ProposedTrade
from tests.risk._helpers import EURUSD, make_settings

S = make_settings()
SYMBOLS = ["EUR/USD", "GBP/USD", "USD/JPY"]

price = st.integers(min_value=1000, max_value=20000).map(lambda n: Decimal(n) / 10000)
direction = st.sampled_from(list(Direction))
rho = st.one_of(st.just(float("nan")), st.floats(min_value=-1, max_value=1))

position = st.builds(
    OpenPosition,
    symbol=st.sampled_from(SYMBOLS),
    direction=direction,
    risk_amount=st.integers(min_value=0, max_value=600).map(Decimal),
)
state_st = st.builds(
    PortfolioState,
    equity=st.integers(min_value=500, max_value=100000).map(Decimal),
    day_start_equity=st.integers(min_value=500, max_value=100000).map(Decimal),
    realized_pnl_today=st.integers(min_value=-5000, max_value=1000).map(Decimal),
    open_positions=st.lists(position, max_size=4),
)
trade_st = st.builds(
    ProposedTrade,
    symbol=st.sampled_from(SYMBOLS),
    direction=direction,
    entry=price,
    stop_loss=price,
    take_profit=price,
)
corr_st = st.dictionaries(
    st.sampled_from([("EUR/USD", "GBP/USD"), ("EUR/USD", "USD/JPY"), ("GBP/USD", "USD/JPY")]),
    rho,
)


@settings(derandomize=True, max_examples=500, deadline=None)
@given(trade=trade_st, state=state_st, corr=corr_st)
def test_approved_never_violates_limits(
    trade: ProposedTrade, state: PortfolioState, corr: dict[tuple[str, str], float]
) -> None:
    d = evaluate_trade(trade, state, corr, EURUSD, S)
    assert d.approved == (not d.reasons)
    if not d.approved:
        assert len(d.messages) == len(d.reasons) == len(set(d.reasons))
        return
    assert d.size is not None and d.size.units > 0
    assert d.size.risk_pct <= S.risk_per_trade_pct
    rr = risk_reward(trade)
    assert rr is not None and rr >= S.min_rr
    assert state.realized_pnl_today > -S.max_daily_loss_pct / 100 * state.day_start_equity
    total = sum((p.risk_amount for p in state.open_positions), Decimal(0)) + d.size.risk_amount
    assert total <= S.max_open_risk_pct / 100 * state.equity
