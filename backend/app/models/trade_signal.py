"""Modelo ORM de `trade_signals` (ampliado en la Fase 3 con el razonamiento, D96)."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.checks import enum_check
from app.schemas.enums import Direction, RegimeLabel, SignalStatus, Timeframe


class TradeSignal(Base):
    __tablename__ = "trade_signals"
    __table_args__ = (
        CheckConstraint(enum_check("timeframe", Timeframe), name="ck_trade_signals_timeframe"),
        CheckConstraint(enum_check("direction", Direction), name="ck_trade_signals_direction"),
        CheckConstraint(enum_check("status", SignalStatus), name="ck_trade_signals_status"),
        CheckConstraint(enum_check("regime", RegimeLabel), name="ck_trade_signals_regime"),
        Index("ix_trade_signals_status_created_at", "status", "created_at"),
        Index("ix_trade_signals_analysis_id", "analysis_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    instrument_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("instruments.id"))
    timeframe: Mapped[str] = mapped_column(Text)
    direction: Mapped[str] = mapped_column(Text)
    entry: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    stop_loss: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    take_profit: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    status: Mapped[str] = mapped_column(
        Text, server_default=text(f"'{SignalStatus.PENDING.value}'")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    analysis_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    rr: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    units: Mapped[Decimal | None] = mapped_column(Numeric(24, 10), nullable=True)
    risk_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 10), nullable=True)
    regime: Mapped[str | None] = mapped_column(Text, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    veto_reasons: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
