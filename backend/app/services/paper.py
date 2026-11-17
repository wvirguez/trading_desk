"""Servicio de paper trading (D135). Por ahora solo `refresh_orders`.

No hace `commit`: lo decide quien llama (D21). El resto (ejecutar señal, blotter, journal)
llega con el grupo 5.
"""

from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.paper_order import PaperOrder
from app.paper.simulator import OrderAdvance, OrderState, advance_order
from app.repositories import ohlcv as ohlcv_repo
from app.repositories import paper_orders as orders_repo
from app.schemas.enums import Direction, OrderStatus, Timeframe
from app.schemas.paper import PaperRefreshResult

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
        adv, n_filled, n_closed, order_warnings = await _advance_all_pages(
            session, order, instrument.symbol
        )
        warnings.extend(f"{instrument.symbol}: {w}" for w in order_warnings)
        filled += n_filled
        closed += n_closed
        if adv.last_processed_ts == order.last_processed_ts and adv.status.value == order.status:
            continue
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
    return PaperRefreshResult(
        orders_checked=len(open_orders),
        orders_filled=filled,
        orders_closed=closed,
        warnings=warnings,
    )
