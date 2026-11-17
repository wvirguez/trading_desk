"""Servicio de paper trading: ejecutar señales, avanzar órdenes, blotter y journal (D133-D138).

No hace `commit`: lo decide quien llama (D21). Si una función lanza una excepción de dominio,
quien llama no debe confirmar la transacción (se descarta con el cierre de la sesión).
El «día» de las guardas y del blotter es UTC (D138).
"""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.instrument import Instrument
from app.models.paper_order import PaperOrder
from app.paper.journal import JournalInput, JournalOrderInput, build_journal
from app.paper.simulator import OrderAdvance, OrderState, advance_order, unrealized_pnl
from app.repositories import instruments as instruments_repo
from app.repositories import ohlcv as ohlcv_repo
from app.repositories import paper_orders as orders_repo
from app.repositories import trade_signals as signals_repo
from app.risk.guards import daily_loss_limit_reached, portfolio_limit_vetoes
from app.schemas.enums import (
    Direction,
    OrderStatus,
    RegimeLabel,
    SignalStatus,
    Timeframe,
    VetoReason,
)
from app.schemas.journal import JournalSchema
from app.schemas.paper import (
    BlotterSchema,
    OrderReceiptSchema,
    PaperOrderSchema,
    PaperRefreshResult,
)
from app.services.backtest import InstrumentNotFoundError
from app.services.portfolio import load_correlation_matrix, load_portfolio_state


class SignalNotFoundError(Exception):
    def __init__(self, signal_id: UUID) -> None:
        super().__init__(f"Señal desconocida: {signal_id}")
        self.signal_id = signal_id


class SignalNotExecutableError(Exception):
    """La señal existe pero no está `APPROVED` (rechazada, pendiente o ya ejecutada)."""

    def __init__(self, signal_id: UUID, status: SignalStatus) -> None:
        if status is SignalStatus.EXECUTED:
            message = f"La señal {signal_id} ya fue ejecutada."
        else:
            message = f"La señal {signal_id} no está aprobada (estado: {status.value})."
        super().__init__(message)
        self.signal_id = signal_id
        self.status = status


class ExecutionVetoedError(Exception):
    """Una guarda de cartera vetó la ejecución con el estado real (D137)."""

    def __init__(self, signal_id: UUID, reasons: list[VetoReason], messages: list[str]) -> None:
        motivos = ", ".join(r.value for r in reasons)
        super().__init__(
            f"La señal {signal_id} no se puede ejecutar: veto de cartera ({motivos}). "
            + " ".join(f"{m}." for m in messages)
            + " El día se mide en UTC."
        )
        self.signal_id = signal_id
        self.reasons = reasons
        self.messages = messages


# Velas leídas por consulta. Cada orden se recorre desde su último avance por páginas
# ascendentes (las más antiguas primero), así que ninguna vela se omite aunque haya más de una
# página pendiente.
_PAGE_SIZE = 5000


def _state(order: PaperOrder) -> OrderState:
    return OrderState(
        direction=Direction(order.direction),
        units=order.units,
        stop_loss=order.stop_loss,
        take_profit=order.take_profit,
        risk_amount=order.risk_amount,
        executed_at=order.executed_at,
        timeframe=Timeframe(order.timeframe),
        status=OrderStatus(order.status),
        fill_price=order.fill_price,
        filled_at=order.filled_at,
        last_processed_ts=order.last_processed_ts,
    )


async def _advance_all_pages(
    session: AsyncSession, order: PaperOrder, symbol: str
) -> tuple[OrderAdvance, int, int, list[str]]:
    """Avanza una orden con todas las velas pendientes, página a página y en orden ascendente.

    Devuelve el avance final, cuántos fills y cierres produjo y los avisos del simulador.
    """
    timeframe = Timeframe(order.timeframe)
    state = _state(order)
    start = order.last_processed_ts or order.executed_at
    if order.last_processed_ts is not None:
        start = order.last_processed_ts + timeframe.duration
    filled = closed = 0
    warnings: list[str] = []
    while True:
        candles = await ohlcv_repo.fetch_forward(
            session, order.instrument_id, timeframe, symbol, start, _PAGE_SIZE
        )
        adv = advance_order(state, candles)
        filled += adv.filled_now
        closed += adv.closed_now
        warnings.extend(adv.warnings)
        if (
            len(candles) < _PAGE_SIZE
            or adv.status in (OrderStatus.CLOSED_TP, OrderStatus.CLOSED_SL)
            or adv.last_processed_ts is None
        ):
            return adv, filled, closed, warnings
        state = replace(
            state,
            status=adv.status,
            fill_price=adv.fill_price,
            filled_at=adv.filled_at,
            last_processed_ts=adv.last_processed_ts,
        )
        start = adv.last_processed_ts + timeframe.duration


async def _refresh_one(
    session: AsyncSession, order: PaperOrder, symbol: str, moment: datetime
) -> tuple[int, int, list[str]]:
    """Avanza una orden y persiste su estado. Devuelve fills, cierres y avisos del simulador."""
    adv, filled, closed, warnings = await _advance_all_pages(session, order, symbol)
    if adv.last_processed_ts != order.last_processed_ts or adv.status.value != order.status:
        await orders_repo.update_order_state(
            session,
            order,
            status=adv.status,
            updated_at=moment,
            fill_price=adv.fill_price,
            filled_at=adv.filled_at,
            exit_price=adv.exit_price,
            closed_at=adv.closed_at,
            realized_pnl=adv.realized_pnl,
            last_processed_ts=adv.last_processed_ts,
        )
    return filled, closed, warnings


async def refresh_orders(session: AsyncSession, now: datetime | None = None) -> PaperRefreshResult:
    """Avanza las órdenes abiertas con las velas ingeridas posteriores a su último avance.

    Lee las velas de cada orden por páginas ascendentes desde su último avance, sin omitir
    ninguna. Idempotente: reprocesar las mismas velas no cambia el estado. No hace `commit`.
    """
    moment = now or datetime.now(UTC)
    open_orders = await orders_repo.list_open_orders(session)

    filled = closed = 0
    warnings: list[str] = []
    for order, instrument in open_orders:
        n_filled, n_closed, order_warnings = await _refresh_one(
            session, order, instrument.symbol, moment
        )
        warnings.extend(f"{instrument.symbol}: {w}" for w in order_warnings)
        filled += n_filled
        closed += n_closed
    return PaperRefreshResult(
        orders_checked=len(open_orders),
        orders_filled=filled,
        orders_closed=closed,
        warnings=warnings,
    )


async def execute_signal(
    session: AsyncSession, settings: Settings, signal_id: UUID, now: datetime | None = None
) -> OrderReceiptSchema:
    """Ejecuta (simulado) una señal `APPROVED` en una transacción con la fila bloqueada (D136).

    Orden: bloqueo `FOR UPDATE` de la señal -> comprobar estado -> avanzar órdenes abiertas ->
    guardas de cartera con el estado real y el `risk_amount` de la señal, sin recalcular el
    tamaño (D137, D147) -> insertar la orden (`UNIQUE(signal_id)`) -> señal `EXECUTED` ->
    avanzar la orden con las velas ya ingeridas. No hace `commit`.
    """
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    signal = await signals_repo.get_signal_for_update(session, signal_id)
    if signal is None:
        raise SignalNotFoundError(signal_id)
    status = SignalStatus(signal.status)
    if status is not SignalStatus.APPROVED:
        raise SignalNotExecutableError(signal_id, status)
    instrument = await session.get(Instrument, signal.instrument_id)
    if instrument is None:  # imposible por la FK; defensa para el tipado
        raise InstrumentNotFoundError(str(signal.instrument_id))

    await refresh_orders(session, moment)  # D135: la cartera parte de órdenes al día
    state, _ = await load_portfolio_state(session, settings, moment)
    instruments = [(r.id, r.symbol) for r in await instruments_repo.list_all(session)]
    timeframe = Timeframe(signal.timeframe)
    correlations = await load_correlation_matrix(
        session, instruments, timeframe, settings.correlation_window
    )
    if signal.risk_amount is None:
        raise ValueError(f"La señal {signal_id} aprobada no tiene tamaño (risk_amount)")
    vetoes = portfolio_limit_vetoes(
        instrument.symbol,
        Direction(signal.direction),
        signal.risk_amount,  # el de la señal, no recalculado (D137)
        state,
        correlations,
        settings,
    )
    if vetoes:
        raise ExecutionVetoedError(signal_id, [r for r, _ in vetoes], [m for _, m in vetoes])

    order = await orders_repo.insert_order(session, signal, moment)
    await signals_repo.mark_executed(session, signal_id)
    _, _, warnings = await _refresh_one(session, order, instrument.symbol, moment)

    po = orders_repo.to_schema(order, instrument.symbol)
    fields = {name: getattr(po, name) for name in OrderReceiptSchema.model_fields}
    fields["warnings"] = warnings
    return OrderReceiptSchema(**fields)


async def get_blotter(
    session: AsyncSession,
    settings: Settings,
    status: OrderStatus | None,
    limit: int,
    now: datetime | None = None,
) -> BlotterSchema:
    """Estado de cartera y órdenes con PnL (solo lectura: no avanza órdenes, D135).

    `mark_price` es el último cierre ingerido del timeframe de la orden (no tiempo real).
    `open_risk`, `unrealized_pnl_total` y `daily_loss_limit_reached` cubren todas las órdenes
    abiertas, aunque `status` o `limit` recorten la lista.
    """
    state, warnings = await load_portfolio_state(session, settings, now)
    total = await orders_repo.sum_realized_pnl(session)

    marks: dict[UUID, Decimal] = {}
    unrealized_total = Decimal(0)
    open_risk = Decimal(0)
    for order, instrument in await orders_repo.list_open_orders(session):
        open_risk += order.risk_amount
        if order.status != OrderStatus.OPEN.value or order.fill_price is None:
            continue
        last = await ohlcv_repo.fetch_latest(
            session, order.instrument_id, Timeframe(order.timeframe), 1, instrument.symbol
        )
        if not last:
            warnings.append(f"{instrument.symbol}: sin velas ingeridas para valorar la orden.")
            continue
        marks[order.id] = last[0].close
        unrealized_total += unrealized_pnl(
            Direction(order.direction), order.fill_price, last[0].close, order.units
        )

    orders: list[PaperOrderSchema] = []
    for order, instrument in await orders_repo.list_orders(session, status, limit):
        base = orders_repo.to_schema(order, instrument.symbol)
        mark = marks.get(order.id)
        if mark is None or order.fill_price is None:
            orders.append(base)
            continue
        pnl = unrealized_pnl(Direction(order.direction), order.fill_price, mark, order.units)
        orders.append(
            PaperOrderSchema(
                **{
                    **dict(base),
                    "mark_price": mark,
                    "unrealized_pnl": pnl,
                    "pnl": pnl,
                    "r_multiple": pnl / order.risk_amount,
                }
            )
        )
    return BlotterSchema(
        equity=state.equity,
        day_start_equity=state.day_start_equity,
        realized_pnl_today=state.realized_pnl_today,
        realized_pnl_total=total,
        unrealized_pnl_total=unrealized_total,
        open_risk=open_risk,
        daily_loss_limit_reached=daily_loss_limit_reached(state, settings),
        orders=orders,
        warnings=warnings,
    )


async def get_journal(session: AsyncSession, symbol: str | None, limit: int) -> JournalSchema:
    """Journal derivado de `trade_signals` y `paper_orders` (D133, D142). Solo lectura."""
    if symbol is not None and await instruments_repo.get_by_symbol(session, symbol) is None:
        raise InstrumentNotFoundError(symbol)
    rows: list[JournalInput] = []
    for signal, instrument, order in await signals_repo.list_for_journal(session, symbol, limit):
        if signal.analysis_id is None or signal.rr is None or signal.regime is None:
            continue  # filas anteriores a la Fase 3 (D142)
        rows.append(
            JournalInput(
                signal_id=signal.id,
                analysis_id=signal.analysis_id,
                created_at=signal.created_at,
                symbol=instrument.symbol,
                timeframe=Timeframe(signal.timeframe),
                direction=Direction(signal.direction),
                signal_status=SignalStatus(signal.status),
                regime=RegimeLabel(signal.regime),
                entry=signal.entry,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                rr=signal.rr,
                veto_reasons=tuple(VetoReason(v) for v in signal.veto_reasons),
                rationale=signal.rationale or "",
                risk_amount=signal.risk_amount,
                order=(
                    JournalOrderInput(
                        order_id=order.id,
                        status=OrderStatus(order.status),
                        risk_amount=order.risk_amount,
                        fill_price=order.fill_price,
                        exit_price=order.exit_price,
                        realized_pnl=order.realized_pnl,
                        closed_at=order.closed_at,
                    )
                    if order is not None
                    else None
                ),
            )
        )
    return build_journal(rows)
