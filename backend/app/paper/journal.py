"""Journal: señal emitida frente a su resultado simulado (D142, D143). Python puro, Decimal.

Paquete puro (principio 2): no importa el ORM. La capa de servicio convierte las filas
`(TradeSignal, Instrument, PaperOrder | None)` en `JournalInput`.

Definiciones del resumen:
- `n_approved`: señales `APPROVED` + `EXECUTED` (aprobadas por las guardas; ejecutadas incluidas).
- `n_rejected`: señales `REJECTED`; `n_executed`: señales `EXECUTED`.
- `n_closed = n_wins + n_losses`: órdenes `CLOSED_TP` (WIN) o `CLOSED_SL` (LOSS).
- `win_rate = n_wins / n_closed`; `total_pnl = Σ realized_pnl` de las cerradas (Decimal).
- `r_multiple = realized_pnl / risk_amount` de la orden; `expectancy_r` y `avg_r_realized` son
  la media de `r_multiple` de las cerradas (la expectancy en R es esa media).
- `avg_rr_emitted`: media de `rr` de TODAS las señales `APPROVED` y `EXECUTED` (las vetadas
  se excluyen: su R:R no es un objetivo que se haya operado ni podido operar).
- Con 0 cerradas las métricas son `None` y `warnings` lleva un aviso de «sin cerradas»
  (distinto del de muestra pequeña, que se emite con 0 < N < 30).
Aritmética en Decimal hasta el último paso; `float` solo en las métricas float del esquema.
Entradas iguales dan salida idéntica; las entradas se ordenan por `created_at` descendente
(desempate por `signal_id`).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from app.schemas.enums import (
    Direction,
    JournalOutcome,
    OrderStatus,
    RegimeLabel,
    SignalStatus,
    Timeframe,
    VetoReason,
)
from app.schemas.journal import JournalEntrySchema, JournalSchema, JournalSummarySchema

MIN_CLOSED_FOR_STATS = 30

_OUTCOMES = {
    OrderStatus.PENDING_FILL: JournalOutcome.PENDING_FILL,
    OrderStatus.OPEN: JournalOutcome.OPEN,
    OrderStatus.CLOSED_TP: JournalOutcome.WIN,
    OrderStatus.CLOSED_SL: JournalOutcome.LOSS,
}


@dataclass(frozen=True)
class JournalOrderInput:
    """Datos de la orden simulada de una señal."""

    order_id: UUID
    status: OrderStatus
    risk_amount: Decimal
    fill_price: Decimal | None = None
    exit_price: Decimal | None = None
    realized_pnl: Decimal | None = None
    closed_at: datetime | None = None


@dataclass(frozen=True)
class JournalInput:
    """Una señal (con `analysis_id`) y su orden opcional, sin ORM."""

    signal_id: UUID
    analysis_id: UUID
    created_at: datetime
    symbol: str
    timeframe: Timeframe
    direction: Direction
    signal_status: SignalStatus
    regime: RegimeLabel
    entry: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    rr: Decimal
    veto_reasons: tuple[VetoReason, ...]
    rationale: str
    risk_amount: Decimal | None = None  # riesgo de la señal (tamaño)
    order: JournalOrderInput | None = None


def _entry(row: JournalInput) -> JournalEntrySchema:
    order = row.order
    r_multiple = (
        order.realized_pnl / order.risk_amount
        if order is not None and order.realized_pnl is not None and order.risk_amount != 0
        else None
    )
    return JournalEntrySchema(
        signal_id=row.signal_id,
        analysis_id=row.analysis_id,
        created_at=row.created_at,
        symbol=row.symbol,
        timeframe=row.timeframe,
        direction=row.direction,
        signal_status=row.signal_status,
        regime=row.regime,
        entry=row.entry,
        stop_loss=row.stop_loss,
        take_profit=row.take_profit,
        rr=row.rr,
        risk_amount=row.risk_amount,
        veto_reasons=list(row.veto_reasons),
        rationale=row.rationale,
        outcome=_OUTCOMES[order.status] if order is not None else JournalOutcome.NOT_EXECUTED,
        order_id=order.order_id if order is not None else None,
        fill_price=order.fill_price if order is not None else None,
        exit_price=order.exit_price if order is not None else None,
        realized_pnl=order.realized_pnl if order is not None else None,
        r_multiple=r_multiple,
        closed_at=order.closed_at if order is not None else None,
    )


def _mean(values: Sequence[Decimal]) -> float | None:
    return float(sum(values, Decimal(0)) / len(values)) if values else None


def build_journal(rows: Sequence[JournalInput]) -> JournalSchema:
    """Entradas (recientes primero) y resumen estadístico del journal."""
    ordered = sorted(rows, key=lambda r: (-r.created_at.timestamp(), str(r.signal_id)))
    entries = [_entry(r) for r in ordered]

    closed = [e for e in entries if e.outcome in (JournalOutcome.WIN, JournalOutcome.LOSS)]
    wins = sum(1 for e in closed if e.outcome is JournalOutcome.WIN)
    n_closed = len(closed)
    r_values = [e.r_multiple for e in closed if e.r_multiple is not None]
    approved = (SignalStatus.APPROVED, SignalStatus.EXECUTED)

    warnings: list[str] = []
    if n_closed == 0:
        warnings.append("Sin operaciones cerradas: las métricas no están disponibles.")
    elif n_closed < MIN_CLOSED_FOR_STATS:
        warnings.append(
            f"Muestra pequeña: {n_closed} operaciones cerradas (< {MIN_CLOSED_FOR_STATS}); "
            "las métricas no son concluyentes."
        )

    expectancy = _mean(r_values)
    summary = JournalSummarySchema(
        n_signals=len(entries),
        n_approved=sum(1 for e in entries if e.signal_status in approved),
        n_rejected=sum(1 for e in entries if e.signal_status is SignalStatus.REJECTED),
        n_executed=sum(1 for e in entries if e.signal_status is SignalStatus.EXECUTED),
        n_closed=n_closed,
        n_wins=wins,
        n_losses=n_closed - wins,
        win_rate=wins / n_closed if n_closed else None,
        total_pnl=sum((e.realized_pnl for e in closed if e.realized_pnl is not None), Decimal(0)),
        expectancy_r=expectancy,
        avg_rr_emitted=_mean([e.rr for e in entries if e.signal_status in approved]),
        avg_r_realized=expectancy,
        warnings=warnings,
    )
    return JournalSchema(summary=summary, entries=entries)
