"""Acceso a `trade_signals` y conversión a `TradeSignalSchema` (D96)."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.instrument import Instrument
from app.models.trade_signal import TradeSignal
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
    """Posiciones abiertas = señales `EXECUTED` (D90; vacío hasta el paper trading, 4.6).

    `risk_amount` nulo (filas anteriores a la Fase 3) cuenta como 0.
    """
    stmt = (
        select(TradeSignal, Instrument.symbol)
        .join(Instrument, Instrument.id == TradeSignal.instrument_id)
        .where(TradeSignal.status == SignalStatus.EXECUTED.value)
        .order_by(TradeSignal.created_at, TradeSignal.id)
    )
    rows = (await session.execute(stmt)).all()
    return [
        OpenPosition(
            symbol=symbol,
            direction=Direction(signal.direction),
            risk_amount=signal.risk_amount if signal.risk_amount is not None else Decimal(0),
        )
        for signal, symbol in rows
    ]
