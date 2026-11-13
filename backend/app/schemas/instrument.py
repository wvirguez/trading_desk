"""Esquema de instrumento negociable."""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator

from app.schemas.enums import AssetClass, Provider, SessionType


class InstrumentSchema(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    asset_class: AssetClass
    provider: Provider
    provider_symbol: str
    base_currency: str
    quote_currency: str
    tick_size: Decimal
    lot_size: Decimal
    session: SessionType

    @field_validator("tick_size", "lot_size")
    @classmethod
    def _positivo(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= 0:
            raise ValueError("El valor debe ser un decimal finito mayor que 0")
        return value
