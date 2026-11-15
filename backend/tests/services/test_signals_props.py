"""Propiedad de D94 / criterio de éxito de la misión: ninguna señal APPROVED incumple el riesgo.

Recorre el camino determinista completo (`evaluate_trade` -> auditor -> `build_trade_signal`) con
niveles, cartera y decisiones del auditor arbitrarios.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from hypothesis import HealthCheck, event, given, settings
from hypothesis import strategies as st

from app.core.config import Settings
from app.risk.guards import evaluate_trade, risk_reward
from app.schemas.agents import (
    MarketStructureReport,
    QuantAlphaReport,
    RiskVerdict,
    TimeframeStructure,
)
from app.schemas.enums import (
    AuditDecision,
    Bias,
    Direction,
    Playbook,
    RegimeLabel,
    SignalStatus,
    Timeframe,
    VetoReason,
)
from app.schemas.quant import RegimeStats
from app.schemas.risk import GuardDecision, OpenPosition, PortfolioState, ProposedTrade
from app.schemas.signals import ProposedSignal, TradeSignalSchema
from app.services.signals import build_trade_signal
from tests.quant._proposal_helpers import SEED

CFG = Settings(_env_file=None)  # type: ignore[call-arg]
INSTRUMENT = SEED["EUR/USD"]
TICK = INSTRUMENT.tick_size
D = Decimal
NOW = datetime(2026, 11, 15, tzinfo=UTC)

STRUCTURE = MarketStructureReport(
    symbol="EUR/USD",
    entry_timeframe=Timeframe.H1,
    timeframes=[
        TimeframeStructure(
            timeframe=tf, bias=Bias.BULLISH, key_levels=[], open_fvg_ts=[], comment="c"
        )
        for tf in (Timeframe.H1, Timeframe.H4)
    ],
    htf_alignment=Bias.BULLISH,
    reasoning="r",
)
QUANT = QuantAlphaReport(
    symbol="EUR/USD",
    timeframe=Timeframe.H1,
    regime=RegimeLabel.TRENDING,
    stats=RegimeStats(hurst=0.6, adf_pvalue=0.5, zscore=1.0, volatility_ratio=1.0, n_obs=300),
    playbook=Playbook.TREND_FOLLOWING,
    reasoning="r",
)


@st.composite
def scenarios(draw: st.DrawFn) -> tuple[ProposedTrade, PortfolioState, AuditDecision]:
    direction = draw(st.sampled_from(Direction))
    entry_ticks = draw(st.integers(min_value=50_000, max_value=200_000))
    stop_ticks = draw(st.integers(min_value=1, max_value=5_000))
    tp_ticks = draw(st.integers(min_value=1, max_value=20_000))
    entry = TICK * entry_ticks
    sign = 1 if direction is Direction.LONG else -1
    stop = entry - sign * TICK * stop_ticks
    target = entry + sign * TICK * tp_ticks
    equity = D(draw(st.integers(min_value=1_000, max_value=1_000_000)))
    pnl_pct = D(draw(st.integers(min_value=-600, max_value=300))) / 100  # -6 % .. +3 %
    positions = [
        OpenPosition(
            symbol=draw(st.sampled_from(["EUR/USD", "XAU/USD", "BTC/USDT"])),
            direction=draw(st.sampled_from(Direction)),
            risk_amount=equity * D(draw(st.integers(min_value=0, max_value=250))) / 10_000,
        )
        for _ in range(draw(st.integers(min_value=0, max_value=3)))
    ]
    state = PortfolioState(
        equity=equity,
        day_start_equity=equity,
        realized_pnl_today=equity * pnl_pct / 100,
        open_positions=positions,
    )
    trade = ProposedTrade(
        symbol="EUR/USD", direction=direction, entry=entry, stop_loss=stop, take_profit=target
    )
    return trade, state, draw(st.sampled_from(AuditDecision))


def _build(
    trade: ProposedTrade, state: PortfolioState, decision: AuditDecision
) -> tuple[GuardDecision, TradeSignalSchema]:
    rr = risk_reward(trade)
    guard = evaluate_trade(trade, state, {}, INSTRUMENT, CFG)
    proposal = ProposedSignal(
        symbol=trade.symbol,
        timeframe=Timeframe.H1,
        direction=trade.direction,
        entry=trade.entry,
        stop_loss=trade.stop_loss,
        take_profit=trade.take_profit,
        rr=rr if rr is not None else D(1),
        source="propiedad",
    )
    verdict = (
        RiskVerdict(decision=decision, deterministic=guard, concerns=["x"], rationale="r")
        if guard.approved
        else None
    )
    signal = build_trade_signal(
        analysis_id=uuid4(),
        instrument=INSTRUMENT,
        proposal=proposal,
        guard=guard,
        verdict=verdict,
        structure=STRUCTURE,
        quant=QUANT,
        created_at=NOW,
    )
    return guard, signal


def _daily_loss_pct(state: PortfolioState) -> Decimal:
    """Pérdida del día en % del capital inicial (positiva = pérdida)."""
    return -state.realized_pnl_today / state.day_start_equity * 100


@settings(derandomize=True, max_examples=300, suppress_health_check=[HealthCheck.too_slow])
@given(scenarios())
def test_ninguna_senal_aprobada_incumple_riesgo_rr_ni_perdida_diaria(
    scenario: tuple[ProposedTrade, PortfolioState, AuditDecision],
) -> None:
    trade, state, decision = scenario
    guard, signal = _build(trade, state, decision)
    event("perdida_diaria_en_limite" if _daily_loss_pct(state) >= CFG.max_daily_loss_pct else "ok")

    if _daily_loss_pct(state) >= CFG.max_daily_loss_pct:
        # Con la pérdida diaria en el límite o por encima, NUNCA hay señal aprobada.
        assert signal.status is SignalStatus.REJECTED
        assert not guard.approved and VetoReason.DAILY_LOSS_LIMIT in signal.veto_reasons
    if signal.status is not SignalStatus.APPROVED:
        assert signal.veto_reasons or "Rechazo del auditor:" in signal.rationale
        return
    assert decision is AuditDecision.APPROVE and guard.approved
    assert signal.size is not None and signal.size.units > 0
    assert signal.size.risk_pct <= CFG.risk_per_trade_pct
    assert signal.size.risk_amount <= state.equity * CFG.risk_per_trade_pct / 100
    assert signal.rr >= CFG.min_rr
    rr = risk_reward(trade)
    assert rr is not None and rr >= CFG.min_rr
    assert _daily_loss_pct(state) < CFG.max_daily_loss_pct  # pérdida diaria < límite
    assert state.realized_pnl_today > -CFG.max_daily_loss_pct / 100 * state.day_start_equity
    assert signal.veto_reasons == []


def test_la_propiedad_de_perdida_diaria_no_es_vacia() -> None:
    """Barrido determinista de PnL: hay señales aprobadas CON pérdida y vetadas en el límite."""
    entry = TICK * 100_000
    trade = ProposedTrade(
        symbol="EUR/USD",
        direction=Direction.LONG,
        entry=entry,
        stop_loss=entry - TICK * 500,
        take_profit=entry + TICK * 1_500,  # R:R 3
    )
    approved_with_loss: list[Decimal] = []
    rejected_at_limit: list[Decimal] = []
    for tenth in range(-60, 31):  # -6.0 % .. +3.0 % en pasos de 0,1 %
        equity = D(10000)
        state = PortfolioState(
            equity=equity,
            day_start_equity=equity,
            realized_pnl_today=equity * D(tenth) / 1000,
            open_positions=[],
        )
        _, signal = _build(trade, state, AuditDecision.APPROVE)
        loss = _daily_loss_pct(state)
        if signal.status is SignalStatus.APPROVED:
            assert loss < CFG.max_daily_loss_pct
            if loss > 0:
                approved_with_loss.append(loss)
        elif loss >= CFG.max_daily_loss_pct:
            assert VetoReason.DAILY_LOSS_LIMIT in signal.veto_reasons
            rejected_at_limit.append(loss)
    assert approved_with_loss, "debe haber señales aprobadas con pérdida diaria menor al límite"
    assert max(approved_with_loss) == CFG.max_daily_loss_pct - D("0.1")
    assert rejected_at_limit and min(rejected_at_limit) == CFG.max_daily_loss_pct
