"""Modelo ORM de `instruments`."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Identity, Numeric, SmallInteger, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.checks import enum_check
from app.schemas.enums import AssetClass, Provider, SessionType


class Instrument(Base):
    __tablename__ = "instruments"
    __table_args__ = (
        CheckConstraint(enum_check("asset_class", AssetClass), name="ck_instruments_asset_class"),
        CheckConstraint(enum_check("provider", Provider), name="ck_instruments_provider"),
        CheckConstraint(enum_check("session", SessionType), name="ck_instruments_session"),
        CheckConstraint("tick_size > 0", name="ck_instruments_tick_size_positivo"),
        CheckConstraint("lot_size > 0", name="ck_instruments_lot_size_positivo"),
    )

    id: Mapped[int] = mapped_column(SmallInteger, Identity(), primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, unique=True)
    asset_class: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(Text)
    provider_symbol: Mapped[str] = mapped_column(Text)
    base_currency: Mapped[str] = mapped_column(Text)
    quote_currency: Mapped[str] = mapped_column(Text)
    tick_size: Mapped[Decimal] = mapped_column(Numeric(20, 10))
    lot_size: Mapped[Decimal] = mapped_column(Numeric(20, 10))
    session: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
