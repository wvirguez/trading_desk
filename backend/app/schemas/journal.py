"""Esquemas del journal: señal emitida frente a su resultado simulado (consulta derivada)."""

from datetime import datetime
from decimal import Decimal
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from app.schemas.enums import (
    Direction,
    JournalOutcome,
    RegimeLabel,
    SignalStatus,
    Timeframe,
    VetoReason,
)

_JOURNAL_CONFIG = ConfigDict(frozen=True, extra="forbid")

_CERRADOS = (JournalOutcome.WIN, JournalOutcome.LOSS)


class JournalEntrySchema(BaseModel):
    """Una señal con su resultado simulado.

    Invariantes:
    - NOT_EXECUTED: sin `order_id` ni datos de orden.
    - PENDING_FILL, OPEN, WIN y LOSS: `order_id` obligatorio.
    - PENDING_FILL: sin `fill_price`.
    - Sin cerrar (todo salvo WIN/LOSS): sin `exit_price`, `realized_pnl`, `r_multiple` ni
      `closed_at`.
    - WIN/LOSS: `fill_price`, `exit_price`, `realized_pnl` y `closed_at` obligatorios.
    """

    model_config = _JOURNAL_CONFIG

    signal_id: UUID
    analysis_id: UUID
    created_at: datetime
    symbol: str
    timeframe: Timeframe
    direction: Direction
    signal_status: SignalStatus
    regime: RegimeLabel
    entry: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    rr: Decimal  # R:R emitido
    risk_amount: Decimal | None = None
    veto_reasons: list[VetoReason]
    rationale: str  # texto del modelo, no verificado (D128)
    outcome: JournalOutcome
    order_id: UUID | None = None
    fill_price: Decimal | None = None
    exit_price: Decimal | None = None
    realized_pnl: Decimal | None = None
    r_multiple: Decimal | None = None  # R realizado
    closed_at: datetime | None = None

    @model_validator(mode="after")
    def _invariantes_de_resultado(self) -> Self:
        res = self.outcome.value
        datos_de_orden = {
            "fill_price": self.fill_price,
            "exit_price": self.exit_price,
            "realized_pnl": self.realized_pnl,
            "r_multiple": self.r_multiple,
            "closed_at": self.closed_at,
        }
        if self.outcome is JournalOutcome.NOT_EXECUTED:
            if self.order_id is not None:
                raise ValueError(
                    f"Una entrada NOT_EXECUTED no puede tener order_id (recibido {self.order_id})"
                )
            con_valor = [n for n, v in datos_de_orden.items() if v is not None]
            if con_valor:
                raise ValueError(
                    "Una entrada NOT_EXECUTED no puede tener datos de orden "
                    f"({', '.join(con_valor)})"
                )
            return self
        if self.order_id is None:
            raise ValueError(f"Una entrada {res} requiere order_id")
        if self.outcome is JournalOutcome.PENDING_FILL and self.fill_price is not None:
            raise ValueError(
                f"Una entrada PENDING_FILL no puede tener fill_price (recibido {self.fill_price})"
            )
        if self.outcome in _CERRADOS:
            faltan = [
                n
                for n in ("fill_price", "exit_price", "realized_pnl", "closed_at")
                if datos_de_orden[n] is None
            ]
            if faltan:
                raise ValueError(f"Una entrada {res} requiere {', '.join(faltan)}")
        else:
            con_valor = [
                n
                for n in ("exit_price", "realized_pnl", "r_multiple", "closed_at")
                if datos_de_orden[n] is not None
            ]
            if con_valor:
                raise ValueError(
                    f"Una entrada {res} no puede tener datos de cierre ({', '.join(con_valor)})"
                )
        return self


class JournalSummarySchema(BaseModel):
    """Resumen estadístico. Las métricas son None sin operaciones cerradas (no 0, no NaN)."""

    model_config = _JOURNAL_CONFIG

    n_signals: int
    n_approved: int
    n_rejected: int
    n_executed: int
    n_closed: int
    n_wins: int
    n_losses: int
    win_rate: float | None = None
    total_pnl: Decimal
    expectancy_r: float | None = None  # media de r_multiple de las cerradas
    avg_rr_emitted: float | None = None
    avg_r_realized: float | None = None
    warnings: list[str] = []

    @model_validator(mode="after")
    def _contadores_coherentes(self) -> Self:
        for nombre in (
            "n_signals", "n_approved", "n_rejected", "n_executed", "n_closed", "n_wins", "n_losses",
        ):  # fmt: skip
            valor: int = getattr(self, nombre)
            if valor < 0:
                raise ValueError(f"{nombre} no puede ser negativo (recibido {valor})")
        if self.n_wins + self.n_losses != self.n_closed:
            raise ValueError(
                f"n_wins + n_losses debe igualar n_closed "
                f"(n_wins={self.n_wins}, n_losses={self.n_losses}, n_closed={self.n_closed})"
            )
        return self


class JournalSchema(BaseModel):
    model_config = _JOURNAL_CONFIG

    summary: JournalSummarySchema
    entries: list[JournalEntrySchema]  # más recientes primero
