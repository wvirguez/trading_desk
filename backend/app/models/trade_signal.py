"""Modelo ORM de `trade_signals` (mínimo; el razonamiento llega en la Fase 3)."""

import uuid
from datetime import datetime
from decimal import Decimal

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
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.checks import enum_check
from app.schemas.enums import Direction, SignalStatus, Timeframe


class TradeSignal(Base):
    __tablename__ = "trade_signals"
    __table_args__ = (
        CheckConstraint(enum_check("timeframe", Timeframe), name="ck_trade_signals_timeframe"),
        CheckConstraint(enum_check("direction", Direction), name="ck_trade_signals_direction"),
        CheckConstraint(enum_check("status", SignalStatus), name="ck_trade_signals_status"),
        Index("ix_trade_signals_status_created_at", "status", "created_at"),
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
