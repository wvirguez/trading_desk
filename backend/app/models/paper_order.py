"""Modelo ORM de `paper_orders`: órdenes del paper trading simulado (D133)."""

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
from app.schemas.enums import Direction, OrderStatus, Timeframe

# Coherencia estado <-> columnas (mismas invariantes que `PaperOrderSchema`).
STATE_CHECK = (
    "(status = 'PENDING_FILL' AND fill_price IS NULL AND filled_at IS NULL "
    "AND exit_price IS NULL AND closed_at IS NULL AND realized_pnl IS NULL) "
    "OR (status = 'OPEN' AND fill_price IS NOT NULL AND filled_at IS NOT NULL "
    "AND exit_price IS NULL AND closed_at IS NULL AND realized_pnl IS NULL) "
    "OR (status IN ('CLOSED_TP', 'CLOSED_SL') AND fill_price IS NOT NULL "
    "AND filled_at IS NOT NULL AND exit_price IS NOT NULL AND closed_at IS NOT NULL "
    "AND realized_pnl IS NOT NULL)"
)


class PaperOrder(Base):
    __tablename__ = "paper_orders"
    __table_args__ = (
        CheckConstraint(enum_check("timeframe", Timeframe), name="ck_paper_orders_timeframe"),
        CheckConstraint(enum_check("direction", Direction), name="ck_paper_orders_direction"),
        CheckConstraint(enum_check("status", OrderStatus), name="ck_paper_orders_status"),
        CheckConstraint(STATE_CHECK, name="ck_paper_orders_status_state"),
        Index("ix_paper_orders_status", "status"),
        Index("ix_paper_orders_closed_at", "closed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    signal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trade_signals.id"), unique=True
    )
    instrument_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("instruments.id"))
    timeframe: Mapped[str] = mapped_column(Text)
    direction: Mapped[str] = mapped_column(Text)
    units: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    signal_entry: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    stop_loss: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    take_profit: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    risk_amount: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    status: Mapped[str] = mapped_column(
        Text, server_default=text(f"'{OrderStatus.PENDING_FILL.value}'")
    )
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fill_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 10), nullable=True)
    exit_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 10), nullable=True)
    realized_pnl: Mapped[Decimal | None] = mapped_column(Numeric(24, 10), nullable=True)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_processed_ts: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
