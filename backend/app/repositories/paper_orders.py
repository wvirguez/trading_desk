"""Acceso a `paper_orders` y conversión a `PaperOrderSchema` (D133).

Los repositorios hacen `flush` pero no `commit`: lo decide quien llama (D21).
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.instrument import Instrument
from app.models.paper_order import PaperOrder
from app.models.trade_signal import TradeSignal
from app.schemas.enums import Direction, OrderStatus, Timeframe
from app.schemas.paper import PaperOrderSchema

_ACTIVE = (OrderStatus.PENDING_FILL.value, OrderStatus.OPEN.value)
_CLOSED = (OrderStatus.CLOSED_TP.value, OrderStatus.CLOSED_SL.value)


async def insert_order(
    session: AsyncSession, signal: TradeSignal, executed_at: datetime
) -> PaperOrder:
    """Crea la orden `PENDING_FILL` copiando niveles y tamaño de la señal (inmutables).

    Una segunda orden para la misma señal viola `UNIQUE(signal_id)` (`IntegrityError` al
    hacer `flush`). Falla si la señal no tiene tamaño (`units`/`risk_amount`).
    """
    if signal.units is None or signal.risk_amount is None:
        raise ValueError(f"La señal {signal.id} no tiene tamaño (units/risk_amount)")
    row = PaperOrder(
        signal_id=signal.id,
        instrument_id=signal.instrument_id,
        timeframe=signal.timeframe,
        direction=signal.direction,
        units=signal.units,
        signal_entry=signal.entry,
        stop_loss=signal.stop_loss,
        take_profit=signal.take_profit,
        risk_amount=signal.risk_amount,
        status=OrderStatus.PENDING_FILL.value,
        executed_at=executed_at,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def list_open_orders(session: AsyncSession) -> list[tuple[PaperOrder, Instrument]]:
    """Órdenes `PENDING_FILL`/`OPEN` con su instrumento, más antiguas primero."""
    stmt = (
        select(PaperOrder, Instrument)
        .join(Instrument, Instrument.id == PaperOrder.instrument_id)
        .where(PaperOrder.status.in_(_ACTIVE))
        .order_by(PaperOrder.executed_at, PaperOrder.id)
    )
    return [(order, instrument) for order, instrument in (await session.execute(stmt)).all()]


async def list_orders(
    session: AsyncSession, status: OrderStatus | None, limit: int
) -> list[tuple[PaperOrder, Instrument]]:
    """Órdenes (opcionalmente de un estado) con su instrumento, `executed_at` descendente."""
    stmt = (
        select(PaperOrder, Instrument)
        .join(Instrument, Instrument.id == PaperOrder.instrument_id)
        .order_by(PaperOrder.executed_at.desc(), PaperOrder.id)
        .limit(limit)
    )
    if status is not None:
        stmt = stmt.where(PaperOrder.status == status.value)
    return [(order, instrument) for order, instrument in (await session.execute(stmt)).all()]


async def sum_realized_pnl(session: AsyncSession) -> Decimal:
    """Σ `realized_pnl` de las órdenes cerradas (0 si no hay)."""
    stmt = select(func.coalesce(func.sum(PaperOrder.realized_pnl), 0)).where(
        PaperOrder.status.in_(_CLOSED)
    )
    return Decimal((await session.execute(stmt)).scalar_one() or 0)


async def sum_realized_pnl_between(
    session: AsyncSession, start: datetime, end: datetime
) -> Decimal:
    """Σ `realized_pnl` de las órdenes cerradas con `start <= closed_at < end` (0 si no hay)."""
    stmt = select(func.coalesce(func.sum(PaperOrder.realized_pnl), 0)).where(
        PaperOrder.status.in_(_CLOSED),
        PaperOrder.closed_at >= start,
        PaperOrder.closed_at < end,
    )
    return Decimal((await session.execute(stmt)).scalar_one() or 0)


async def update_order_state(
    session: AsyncSession,
    order: PaperOrder,
    *,
    status: OrderStatus,
    updated_at: datetime,
    fill_price: Decimal | None = None,
    filled_at: datetime | None = None,
    exit_price: Decimal | None = None,
    closed_at: datetime | None = None,
    realized_pnl: Decimal | None = None,
    last_processed_ts: datetime | None = None,
) -> PaperOrder:
    """Avanza el estado de la orden. Solo toca columnas de estado, nunca las inmutables.

    Un argumento `None` deja la columna como estaba (el estado solo avanza, no se anula).
    El `CHECK` de coherencia rechaza combinaciones inválidas al hacer `flush`.
    """
    order.status = status.value
    order.updated_at = updated_at
    for name, value in (
        ("fill_price", fill_price),
        ("filled_at", filled_at),
        ("exit_price", exit_price),
        ("closed_at", closed_at),
        ("realized_pnl", realized_pnl),
        ("last_processed_ts", last_processed_ts),
    ):
        if value is not None:
            setattr(order, name, value)
    await session.flush()
    return order


def to_schema(row: PaperOrder, symbol: str) -> PaperOrderSchema:
    """Reconstruye `PaperOrderSchema`; `pnl` es el realizado (cerrada) y `r_multiple` su razón."""
    pnl = row.realized_pnl
    return PaperOrderSchema(
        order_id=row.id,
        signal_id=row.signal_id,
        symbol=symbol,
        timeframe=Timeframe(row.timeframe),
        direction=Direction(row.direction),
        units=row.units,
        signal_entry=row.signal_entry,
        stop_loss=row.stop_loss,
        take_profit=row.take_profit,
        risk_amount=row.risk_amount,
        status=OrderStatus(row.status),
        executed_at=row.executed_at,
        fill_price=row.fill_price,
        filled_at=row.filled_at,
        closed_at=row.closed_at,
        exit_price=row.exit_price,
        realized_pnl=pnl,
        pnl=pnl,
        r_multiple=pnl / row.risk_amount if pnl is not None else None,
    )


async def get_by_signal(session: AsyncSession, signal_id: UUID) -> PaperOrder | None:
    """Orden de una señal, si existe."""
    stmt = select(PaperOrder).where(PaperOrder.signal_id == signal_id)
    return (await session.execute(stmt)).scalar_one_or_none()
