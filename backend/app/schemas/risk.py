"""Esquemas del núcleo de riesgo determinista. El dinero viaja siempre en Decimal."""

from decimal import Decimal
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from app.schemas.enums import Direction, VetoReason


class PositionSizeResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    units: Decimal
    risk_amount: Decimal  # riesgo real
    risk_pct: Decimal  # real, <= pedido
    stop_distance: Decimal
    notional: Decimal


class KellyResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    full_kelly: float
    fraction: float  # aplicada
    capped: bool


class OpenPosition(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    direction: Direction
    risk_amount: Decimal


class PortfolioState(BaseModel):
    model_config = ConfigDict(frozen=True)

    equity: Decimal
    day_start_equity: Decimal
    realized_pnl_today: Decimal
    open_positions: list[OpenPosition]


class ProposedTrade(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    direction: Direction
    entry: Decimal
    stop_loss: Decimal
    take_profit: Decimal


class GuardDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    approved: bool
    reasons: list[VetoReason]
    messages: list[str]  # en español, con el dato que incumple
    rr: Decimal | None = None
    size: PositionSizeResult | None = None

    @model_validator(mode="after")
    def _aprobada_sin_motivos(self) -> Self:
        if self.approved and self.reasons:
            raise ValueError("Una decisión aprobada no puede tener motivos de veto")
        return self
