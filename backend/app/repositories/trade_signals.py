"""Acceso a `trade_signals` y conversión a `TradeSignalSchema` (D96)."""

from datetime import datetime
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.instrument import Instrument
from app.models.paper_order import PaperOrder
from app.models.trade_signal import TradeSignal
from app.repositories import paper_orders as paper_orders_repo
from app.schemas.enums import (
    AssetClass,
    Direction,
    RegimeLabel,
    SignalStatus,
    Timeframe,
    VetoReason,
)
from app.schemas.risk import OpenPosition, PositionSizeResult
from app.schemas.signals import TradeSignalSchema

if TYPE_CHECKING:
    from sqlalchemy.engine import CursorResult

_HUNDRED = 100


async def insert_signal(
    session: AsyncSession, signal: TradeSignalSchema, instrument_id: int
) -> TradeSignal:
    """Inserta la señal (APPROVED o REJECTED) con su `analysis_id` y la devuelve.

    Hace `flush` pero no `commit`: lo decide quien llama (D21). Se conservan `id` y
    `created_at` del esquema. `size` se guarda como `units` y `risk_amount`.
    """
    row = TradeSignal(
        id=signal.id,
        instrument_id=instrument_id,
        timeframe=signal.timeframe.value,
        direction=signal.direction.value,
        entry=signal.entry,
        stop_loss=signal.stop_loss,
        take_profit=signal.take_profit,
        status=signal.status.value,
        created_at=signal.created_at,
        updated_at=signal.created_at,
        analysis_id=signal.analysis_id,
        rr=signal.rr,
        units=signal.size.units if signal.size else None,
        risk_amount=signal.size.risk_amount if signal.size else None,
        regime=signal.regime.value,
        rationale=signal.rationale,
        veto_reasons=[reason.value for reason in signal.veto_reasons],
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


def to_schema(row: TradeSignal, instrument: Instrument) -> TradeSignalSchema:
    """Reconstruye el esquema canónico; falla si la fila es anterior a la Fase 3.

    `size` se rearma con lo guardado (`units`, `risk_amount`) y lo derivable: `stop_distance`,
    `notional = units * entry` y `risk_pct = risk_amount / ACCOUNT_EQUITY_USD * 100` (D90).
    """
    if row.analysis_id is None or row.rr is None or row.regime is None:
        raise ValueError(f"La señal {row.id} no tiene datos de la Fase 3 (analysis_id/rr/regime)")
    size: PositionSizeResult | None = None
    if row.units is not None and row.risk_amount is not None:
        equity = get_settings().account_equity_usd
        size = PositionSizeResult(
            units=row.units,
            risk_amount=row.risk_amount,
            risk_pct=row.risk_amount / equity * _HUNDRED,
            stop_distance=abs(row.entry - row.stop_loss),
            notional=row.units * row.entry,
        )
    return TradeSignalSchema(
        id=row.id,
        analysis_id=row.analysis_id,
        symbol=instrument.symbol,
        asset_class=AssetClass(instrument.asset_class),
        timeframe=Timeframe(row.timeframe),
        direction=Direction(row.direction),
        entry=row.entry,
        stop_loss=row.stop_loss,
        take_profit=row.take_profit,
        rr=row.rr,
        size=size,
        status=SignalStatus(row.status),
        regime=RegimeLabel(row.regime),
        rationale=row.rationale or "",
        veto_reasons=[VetoReason(v) for v in row.veto_reasons],
        created_at=row.created_at,
    )


async def list_active(
    session: AsyncSession, asset_class: AssetClass | None, limit: int
) -> list[TradeSignalSchema]:
    """Señales `APPROVED` (con datos de la Fase 3), más recientes primero."""
    stmt = (
        select(TradeSignal, Instrument)
        .join(Instrument, Instrument.id == TradeSignal.instrument_id)
        .where(
            TradeSignal.status == SignalStatus.APPROVED.value,
            TradeSignal.analysis_id.is_not(None),
            TradeSignal.rr.is_not(None),
            TradeSignal.regime.is_not(None),
        )
        .order_by(TradeSignal.created_at.desc(), TradeSignal.id)
        .limit(limit)
    )
    if asset_class is not None:
        stmt = stmt.where(Instrument.asset_class == asset_class.value)
    rows = (await session.execute(stmt)).all()
    return [to_schema(signal, instrument) for signal, instrument in rows]


async def list_executed(session: AsyncSession) -> list[OpenPosition]:
    """Posiciones abiertas = órdenes `PENDING_FILL`/`OPEN` de `paper_orders` (D138)."""
    rows = await paper_orders_repo.list_open_orders(session)
    return [
        OpenPosition(
            symbol=instrument.symbol,
            direction=Direction(order.direction),
            risk_amount=order.risk_amount,
        )
        for order, instrument in rows
    ]


async def get_signal_for_update(session: AsyncSession, signal_id: UUID) -> TradeSignal | None:
    """Lee la señal bloqueando su fila (`FOR UPDATE`) hasta el fin de la transacción (D136)."""
    stmt = (
        select(TradeSignal)
        .where(TradeSignal.id == signal_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def mark_executed(session: AsyncSession, signal_id: UUID) -> None:
    """Pasa la señal `APPROVED` a `EXECUTED`; falla si no existe o no estaba aprobada."""
    stmt = (
        update(TradeSignal)
        .where(TradeSignal.id == signal_id, TradeSignal.status == SignalStatus.APPROVED.value)
        .values(status=SignalStatus.EXECUTED.value, updated_at=func.now())
        .execution_options(synchronize_session="fetch")
    )
    result = await session.execute(stmt)
    if cast("CursorResult[Any]", result).rowcount != 1:
        raise ValueError(f"La señal {signal_id} no existe o no está APPROVED")
    await session.flush()


async def list_for_journal(
    session: AsyncSession, symbol: str | None, limit: int
) -> list[tuple[TradeSignal, Instrument, PaperOrder | None]]:
    """Señales de todos los estados con `analysis_id` y su orden (LEFT JOIN), recientes primero."""
    stmt = (
        select(TradeSignal, Instrument, PaperOrder)
        .join(Instrument, Instrument.id == TradeSignal.instrument_id)
        .outerjoin(PaperOrder, PaperOrder.signal_id == TradeSignal.id)
        .where(TradeSignal.analysis_id.is_not(None))
        .order_by(TradeSignal.created_at.desc(), TradeSignal.id)
        .limit(limit)
    )
    if symbol is not None:
        stmt = stmt.where(Instrument.symbol == symbol)
    return [(sig, inst, order) for sig, inst, order in (await session.execute(stmt)).all()]


async def list_approved_since(
    session: AsyncSession, symbol: str, since: datetime
) -> list[TradeSignalSchema]:
    """Señales `APPROVED` del símbolo creadas **después** de `since`, ascendente por `created_at`.

    Excluye filas anteriores a la Fase 3 (sin `analysis_id`).
    """
    stmt = (
        select(TradeSignal, Instrument)
        .join(Instrument, Instrument.id == TradeSignal.instrument_id)
        .where(
            Instrument.symbol == symbol,
            TradeSignal.status == SignalStatus.APPROVED.value,
            TradeSignal.analysis_id.is_not(None),
            TradeSignal.rr.is_not(None),
            TradeSignal.regime.is_not(None),
            TradeSignal.created_at > since,
        )
        .order_by(TradeSignal.created_at.asc(), TradeSignal.id)
    )
    rows = (await session.execute(stmt)).all()
    return [to_schema(signal, instrument) for signal, instrument in rows]
