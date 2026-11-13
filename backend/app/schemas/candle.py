"""Esquema de vela OHLCV normalizada (ts = apertura, en UTC)."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.schemas.enums import Timeframe


class CandleSchema(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    timeframe: Timeframe
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    @field_validator("ts")
    @classmethod
    def _ts_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("ts debe incluir zona horaria (se rechazan fechas naive)")
        return value.astimezone(UTC)

    @field_validator("open", "high", "low", "close")
    @classmethod
    def _precio_positivo(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= 0:
            raise ValueError("El precio debe ser un decimal finito mayor que 0")
        return value

    @field_validator("volume")
    @classmethod
    def _volumen_no_negativo(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value < 0:
            raise ValueError("El volumen debe ser un decimal finito mayor o igual que 0")
        return value

    @model_validator(mode="after")
    def _coherencia(self) -> Self:
        if self.timeframe.floor(self.ts) != self.ts:
            raise ValueError(
                f"ts {self.ts.isoformat()} no está alineado con el timeframe {self.timeframe.value}"
            )
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high debe ser mayor o igual que open, close y low")
        if self.low > min(self.open, self.close):
            raise ValueError("low debe ser menor o igual que open y close")
        return self
