"""Modelo ORM de `ohlcv_bars` (hypertable de TimescaleDB sobre `ts`)."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, SmallInteger, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.checks import enum_check
from app.schemas.enums import Timeframe

OHLC_CHECK = (
    "high >= GREATEST(open, close, low) AND low <= LEAST(open, close) "
    "AND open > 0 AND high > 0 AND low > 0 AND close > 0 AND volume >= 0"
)


class OhlcvBar(Base):
    __tablename__ = "ohlcv_bars"
    __table_args__ = (
        CheckConstraint(enum_check("timeframe", Timeframe), name="ck_ohlcv_bars_timeframe"),
        CheckConstraint(OHLC_CHECK, name="ck_ohlcv_bars_ohlc"),
    )

    instrument_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("instruments.id"), primary_key=True
    )
    timeframe: Mapped[str] = mapped_column(Text, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    open: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    high: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    low: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    close: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    volume: Mapped[Decimal] = mapped_column(Numeric(30, 10))
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
