"""Esquemas del motor cuantitativo: estructura de mercado, régimen y backtest."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.enums import Direction, RegimeLabel, StructureEventType, SwingKind, Timeframe


def _a_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("La fecha debe incluir zona horaria (se rechazan fechas naive)")
    return value.astimezone(UTC)


class SwingPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    ts: datetime
    kind: SwingKind
    price: Decimal
    confirmed_at: datetime  # vela en que el swing se confirma (D55)


class StructureEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    ts: datetime  # vela que rompe
    type: StructureEventType
    direction: Direction  # sentido de la ruptura
    broken_swing_ts: datetime
    level: Decimal


class FairValueGap(BaseModel):
    model_config = ConfigDict(frozen=True)

    ts: datetime  # vela central
    direction: Direction
    low: Decimal
    high: Decimal
    mitigated_at: datetime | None = None


class MarketStructureResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    swings: list[SwingPoint]
    events: list[StructureEvent]
    fvgs: list[FairValueGap]


class RegimeStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    hurst: float
    adf_pvalue: float
    zscore: float
    volatility_ratio: float
    n_obs: int


class RegimeThresholds(BaseModel):
    model_config = ConfigDict(frozen=True)

    hurst_mean_reverting: float = 0.45
    hurst_trending: float = 0.55
    adf_alpha: float = 0.05
    vol_ratio_high: float = 1.5
    min_obs: int = 100


class RegimeReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: RegimeLabel
    stats: RegimeStats
    thresholds: RegimeThresholds


class BacktestConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    timeframe: Timeframe
    start: datetime | None = None
    end: datetime | None = None
    initial_capital: Decimal = Decimal(10000)
    zscore_window: int = Field(default=50, ge=10, le=500)
    entry_z: float = 2.0
    exit_z: float = 0.0
    allow_short: bool = True

    @field_validator("symbol")
    @classmethod
    def _symbol_no_vacio(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("symbol no puede estar vacío")
        return value

    @field_validator("start", "end")
    @classmethod
    def _fecha_utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _a_utc(value)

    @field_validator("initial_capital")
    @classmethod
    def _capital_positivo(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= 0:
            raise ValueError("initial_capital debe ser un decimal finito mayor que 0")
        return value

    @field_validator("entry_z")
    @classmethod
    def _entry_positivo(cls, value: float) -> float:
        if not value > 0 or value == float("inf"):
            raise ValueError("entry_z debe ser un número finito mayor que 0")
        return value

    @field_validator("exit_z")
    @classmethod
    def _exit_no_negativo(cls, value: float) -> float:
        if not value >= 0 or value == float("inf"):
            raise ValueError("exit_z debe ser un número finito mayor o igual que 0")
        return value

    @model_validator(mode="after")
    def _coherencia(self) -> Self:
        if self.exit_z >= self.entry_z:
            raise ValueError(f"exit_z ({self.exit_z}) debe ser menor que entry_z ({self.entry_z})")
        if self.start is not None and self.end is not None and self.start >= self.end:
            raise ValueError("start debe ser anterior a end")
        return self


class EquityPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    ts: datetime
    equity: Decimal


class BacktestMetricsSchema(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy_id: UUID
    config: BacktestConfig
    n_bars: int
    n_trades: int
    total_return: float
    sharpe: float
    max_drawdown: float
    win_rate: float
    expectancy: float
    final_equity: Decimal
    equity_curve: list[EquityPoint]
    warnings: list[str]
