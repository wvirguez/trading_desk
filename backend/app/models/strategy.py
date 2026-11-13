"""Modelo ORM de `strategies`: una fila por backtest ejecutado (D63/D64)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, SmallInteger, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.checks import enum_check
from app.schemas.enums import Timeframe


class Strategy(Base):
    __tablename__ = "strategies"
    __table_args__ = (
        CheckConstraint(enum_check("timeframe", Timeframe), name="ck_strategies_timeframe"),
        Index("ix_strategies_instrument_id_created_at", "instrument_id", text("created_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    name: Mapped[str] = mapped_column(Text)
    instrument_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("instruments.id"))
    timeframe: Mapped[str] = mapped_column(Text)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB)
    config_hash: Mapped[str] = mapped_column(Text)
    data_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    data_to: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
