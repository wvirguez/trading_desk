"""Guardas de riesgo y veto determinista (D62, D63).

``evaluate_trade`` evalúa TODAS las guardas, en orden fijo, y acumula los motivos (sin cortar
en la primera). Solo con cero motivos la decisión queda aprobada.

Decisiones:
- ``size`` es ``None`` solo cuando los niveles son inválidos (no hay tamaño calculable); con
  cualquier otro veto se devuelve el tamaño calculado, para trazabilidad.
- ``RISK_PER_TRADE_EXCEEDED`` es una defensa: ``position_size`` redondea hacia abajo y nunca
  supera el riesgo pedido, así que en la práctica no debería dispararse.
- El riesgo del nuevo trade en los límites de cartera es el ``risk_amount`` real del tamaño.
- Un capital (``equity``/``day_start_equity``) <= 0 lanza ``ValueError`` (estado corrupto).
- Correlaciones ``nan`` o par ausente cuentan como 1.0 (D63); mismo símbolo abierto, rho = 1.
"""

import math
from decimal import ROUND_DOWN, Decimal

from app.core.config import Settings
from app.risk.correlation import pair_correlation
from app.risk.sizing import position_size
from app.schemas.enums import Direction, VetoReason
from app.schemas.instrument import InstrumentSchema
from app.schemas.risk import GuardDecision, PortfolioState, PositionSizeResult, ProposedTrade

_HUNDRED = Decimal(100)


def _levels_valid(trade: ProposedTrade) -> bool:
    if min(trade.entry, trade.stop_loss, trade.take_profit) <= 0:
        return False
    if trade.direction is Direction.LONG:
        return trade.stop_loss < trade.entry < trade.take_profit
    return trade.take_profit < trade.entry < trade.stop_loss


def risk_reward(trade: ProposedTrade) -> Decimal | None:
    """|TP - entry| / |entry - SL|; ``None`` si los niveles son inválidos."""
    if not _levels_valid(trade):
        return None
    return abs(trade.take_profit - trade.entry) / abs(trade.entry - trade.stop_loss)


def _f(value: Decimal) -> str:
    return f"{value:.2f}"


def _f_down(value: Decimal) -> str:
    """Trunca a 2 decimales: un R:R de 1.7999 no debe mostrarse como 1.80."""
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_DOWN):.2f}"


def daily_loss_limit_reached(state: PortfolioState, settings: Settings) -> bool:
    """¿La pérdida realizada del día alcanza el límite? Exactamente en el límite, sí."""
    limit_loss = -settings.max_daily_loss_pct / _HUNDRED * state.day_start_equity
    return state.realized_pnl_today <= limit_loss


def portfolio_limit_vetoes(
    symbol: str,
    direction: Direction,
    new_risk: Decimal,
    state: PortfolioState,
    correlations: dict[tuple[str, str], float],
    settings: Settings,
) -> list[tuple[VetoReason, str]]:
    """Guardas de cartera con un riesgo dado (D147): pérdida diaria, riesgo abierto y correlado.

    No calcula tamaño: ``new_risk`` es el riesgo ya fijado del trade (el de la señal al
    ejecutarla, D137; el del tamaño recién calculado al proponerla). Devuelve los vetos en el
    orden fijo ``DAILY_LOSS_LIMIT``, ``OPEN_RISK_LIMIT``, ``CORRELATED_RISK_LIMIT``.
    Capital <= 0 lanza ``ValueError`` (estado corrupto).
    """
    if state.equity <= 0 or state.day_start_equity <= 0:
        raise ValueError("El capital del estado de cartera debe ser mayor que 0")

    vetoes: list[tuple[VetoReason, str]] = []

    # Pérdida diaria: exactamente en el límite veta.
    if daily_loss_limit_reached(state, settings):
        pct = state.realized_pnl_today / state.day_start_equity * _HUNDRED
        shown = f"\u2212{_f(abs(pct))}" if pct < 0 else _f(pct)
        vetoes.append(
            (
                VetoReason.DAILY_LOSS_LIMIT,
                f"Pérdida diaria {shown} % alcanza el límite de {settings.max_daily_loss_pct} %",
            )
        )

    new_pct = new_risk / state.equity * _HUNDRED

    existing = sum((p.risk_amount for p in state.open_positions), Decimal(0))
    existing_pct = existing / state.equity * _HUNDRED
    if existing + new_risk > settings.max_open_risk_pct / _HUNDRED * state.equity:
        vetoes.append(
            (
                VetoReason.OPEN_RISK_LIMIT,
                f"Riesgo abierto {_f(existing_pct + new_pct)} % (existente {_f(existing_pct)} % + "
                f"nuevo {_f(new_pct)} %) supera el máximo {settings.max_open_risk_pct} %",
            )
        )

    threshold = float(settings.correlation_threshold)
    correlated = Decimal(0)
    for pos in state.open_positions:
        if pos.direction is not direction:
            continue
        if pos.symbol == symbol:
            rho = 1.0
        else:
            rho = pair_correlation(correlations, symbol, pos.symbol)
            if math.isnan(rho):
                rho = 1.0
        if abs(rho) >= threshold:
            correlated += pos.risk_amount
    if correlated + new_risk > settings.max_correlated_risk_pct / _HUNDRED * state.equity:
        corr_pct = correlated / state.equity * _HUNDRED
        vetoes.append(
            (
                VetoReason.CORRELATED_RISK_LIMIT,
                f"Riesgo correlacionado {_f(corr_pct + new_pct)} % (existente {_f(corr_pct)} % + "
                f"nuevo {_f(new_pct)} %) supera el máximo {settings.max_correlated_risk_pct} %",
            )
        )
    return vetoes


def evaluate_trade(
    trade: ProposedTrade,
    state: PortfolioState,
    correlations: dict[tuple[str, str], float],
    instrument: InstrumentSchema,
    settings: Settings,
) -> GuardDecision:
    """Evalúa todas las guardas de cartera y devuelve la decisión (D62)."""
    if state.equity <= 0 or state.day_start_equity <= 0:
        raise ValueError("El capital del estado de cartera debe ser mayor que 0")

    reasons: list[VetoReason] = []
    messages: list[str] = []

    def veto(reason: VetoReason, message: str) -> None:
        if reason not in reasons:
            reasons.append(reason)
            messages.append(message)

    rr = risk_reward(trade)
    size: PositionSizeResult | None = None
    if rr is None:
        veto(
            VetoReason.INVALID_LEVELS,
            f"Niveles inválidos para {trade.direction.value}: entrada {trade.entry}, "
            f"stop {trade.stop_loss}, objetivo {trade.take_profit}",
        )
    else:
        size = position_size(
            state.equity, settings.risk_per_trade_pct, trade.entry, trade.stop_loss, instrument
        )
        if rr < settings.min_rr:
            veto(
                VetoReason.RR_BELOW_MIN,
                f"R:R {_f_down(rr)} por debajo del mínimo {settings.min_rr}",
            )

    new_risk = size.risk_amount if size is not None else Decimal(0)
    for reason, message in portfolio_limit_vetoes(
        trade.symbol, trade.direction, new_risk, state, correlations, settings
    ):
        veto(reason, message)

    if size is not None:
        if size.risk_pct > settings.risk_per_trade_pct:
            veto(
                VetoReason.RISK_PER_TRADE_EXCEEDED,
                f"Riesgo por operación {_f(size.risk_pct)} % supera el máximo "
                f"{settings.risk_per_trade_pct} %",
            )
        if size.units == 0:
            veto(
                VetoReason.SIZE_BELOW_LOT,
                f"El tamaño calculado queda por debajo del lote mínimo {instrument.lot_size}",
            )

    return GuardDecision(approved=not reasons, reasons=reasons, messages=messages, rr=rr, size=size)
