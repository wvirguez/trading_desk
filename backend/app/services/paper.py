"""Servicio de paper trading (D135). Por ahora solo `refresh_orders`.

No hace `commit`: lo decide quien llama (D21). El resto (ejecutar señal, blotter, journal)
llega con el grupo 5.
"""

from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.instrument import Instrument
from app.models.paper_order import PaperOrder
from app.paper.simulator import OrderState, advance_order
from app.repositories import ohlcv as ohlcv_repo
from app.repositories import paper_orders as orders_repo
from app.schemas.candle import CandleSchema
from app.schemas.enums import Direction, OrderStatus, Timeframe
from app.schemas.paper import PaperRefreshResult

# Tope de velas leídas por (instrumento, timeframe) en un refresco; un avance posterior
# recoge el resto porque `last_processed_ts` es incremental.
_MAX_CANDLES = 5000


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


async def refresh_orders(session: AsyncSession, now: datetime | None = None) -> PaperRefreshResult:
    """Avanza las órdenes abiertas con las velas ingeridas posteriores a su último avance.

    Idempotente: reprocesar las mismas velas no cambia el estado. No hace `commit`.
    """
    moment = now or datetime.now(UTC)
    open_orders = await orders_repo.list_open_orders(session)
    groups: dict[tuple[int, Timeframe], list[tuple[PaperOrder, Instrument]]] = defaultdict(list)
    for order, instrument in open_orders:
        groups[(order.instrument_id, Timeframe(order.timeframe))].append((order, instrument))

    filled = closed = 0
    warnings: list[str] = []
    for (instrument_id, timeframe), members in groups.items():
        start = min(o.last_processed_ts or o.executed_at for o, _ in members)
        candles: list[CandleSchema] = await ohlcv_repo.fetch_range(
            session, instrument_id, timeframe, members[0][1].symbol, start, None, _MAX_CANDLES
        )
        for order, instrument in members:
            adv = advance_order(_state(order), candles)
            warnings.extend(f"{instrument.symbol}: {w}" for w in adv.warnings)
            filled += adv.filled_now
            closed += adv.closed_now
            if (
                adv.last_processed_ts == order.last_processed_ts
                and adv.status.value == order.status
            ):
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
