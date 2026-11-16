"""Esquemas del paper trading simulado. Precios y dinero en Decimal (en JSON, cadena)."""

from datetime import datetime
from decimal import Decimal
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from app.schemas.enums import Direction, OrderStatus, Timeframe

_PAPER_CONFIG = ConfigDict(frozen=True, extra="forbid")

_CLOSED = (OrderStatus.CLOSED_TP, OrderStatus.CLOSED_SL)


def _positivo(nombre: str, valor: Decimal) -> None:
    if not valor.is_finite() or valor <= 0:
        raise ValueError(f"{nombre} debe ser un decimal finito mayor que 0 (recibido {valor})")


class OrderReceiptSchema(BaseModel):
    """Recibo de una orden simulada.

    Invariantes:
    - PENDING_FILL: sin `fill_price` ni `filled_at`.
    - OPEN y CLOSED_*: `fill_price` y `filled_at` obligatorios.
    - `simulated` es siempre True: no existe ejecución real.
    """

    model_config = _PAPER_CONFIG

    order_id: UUID
    signal_id: UUID
    symbol: str
    timeframe: Timeframe
    direction: Direction
    units: Decimal
    signal_entry: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    risk_amount: Decimal
    status: OrderStatus
    executed_at: datetime
    fill_price: Decimal | None = None
    filled_at: datetime | None = None
    simulated: Literal[True] = True
    warnings: list[str] = []

    @model_validator(mode="after")
    def _invariantes_de_fill(self) -> Self:
        for nombre in ("units", "signal_entry", "stop_loss", "take_profit", "risk_amount"):
            _positivo(nombre, getattr(self, nombre))
        if self.status is OrderStatus.PENDING_FILL:
            if self.fill_price is not None or self.filled_at is not None:
                raise ValueError(
                    "Una orden PENDING_FILL no puede tener fill_price ni filled_at "
                    f"(fill_price={self.fill_price}, filled_at={self.filled_at})"
                )
        else:
            if self.fill_price is None or self.filled_at is None:
                raise ValueError(
                    f"Una orden {self.status.value} requiere fill_price y filled_at "
                    f"(fill_price={self.fill_price}, filled_at={self.filled_at})"
                )
            _positivo("fill_price", self.fill_price)
        return self


class PaperOrderSchema(OrderReceiptSchema):
    """Orden con su evolución: salida, PnL realizado (cerradas) y no realizado (OPEN).

    Invariantes adicionales:
    - CLOSED_*: `exit_price`, `closed_at` y `realized_pnl` obligatorios.
    - No cerrada: sin `exit_price`, `closed_at` ni `realized_pnl`.
    - `mark_price` y `unrealized_pnl` solo en OPEN.
    - `pnl` es el realizado (cerrada), el no realizado (OPEN) o None (PENDING_FILL);
      `r_multiple` (`pnl / risk_amount`) solo existe si hay `pnl`.
    """

    closed_at: datetime | None = None
    exit_price: Decimal | None = None
    realized_pnl: Decimal | None = None
    mark_price: Decimal | None = None
    unrealized_pnl: Decimal | None = None
    pnl: Decimal | None = None
    r_multiple: Decimal | None = None

    @model_validator(mode="after")
    def _invariantes_de_estado(self) -> Self:
        estado = self.status.value
        if self.status in _CLOSED:
            faltan = [
                n for n in ("exit_price", "closed_at", "realized_pnl") if getattr(self, n) is None
            ]
            if faltan:
                raise ValueError(f"Una orden {estado} requiere {', '.join(faltan)}")
            if self.exit_price is not None:
                _positivo("exit_price", self.exit_price)
        else:
            if self.realized_pnl is not None:
                raise ValueError(
                    f"realized_pnl solo existe en órdenes cerradas (estado {estado}, "
                    f"realized_pnl={self.realized_pnl})"
                )
            if self.exit_price is not None or self.closed_at is not None:
                raise ValueError(
                    f"Una orden {estado} no puede tener exit_price ni closed_at "
                    f"(exit_price={self.exit_price}, closed_at={self.closed_at})"
                )
        if self.status is not OrderStatus.OPEN and (
            self.mark_price is not None or self.unrealized_pnl is not None
        ):
            raise ValueError(
                "mark_price y unrealized_pnl solo existen en órdenes OPEN "
                f"(estado {estado}, mark_price={self.mark_price}, "
                f"unrealized_pnl={self.unrealized_pnl})"
            )
        if self.status is OrderStatus.PENDING_FILL:
            esperado, tipo = None, "None"
        elif self.status is OrderStatus.OPEN:
            esperado, tipo = self.unrealized_pnl, "igual a unrealized_pnl"
        else:
            esperado, tipo = self.realized_pnl, "igual a realized_pnl"
        if self.pnl != esperado:
            raise ValueError(
                f"En una orden {estado}, pnl debe ser {tipo} (pnl={self.pnl}, esperado={esperado})"
            )
        if self.r_multiple is not None and self.pnl is None:
            raise ValueError(
                f"r_multiple requiere pnl (estado {estado}, r_multiple={self.r_multiple})"
            )
        return self


class BlotterSchema(BaseModel):
    """Estado de cartera simulada y sus órdenes. Calculado en el backend (principio 2)."""

    model_config = _PAPER_CONFIG

    equity: Decimal
    day_start_equity: Decimal
    realized_pnl_today: Decimal
    realized_pnl_total: Decimal
    unrealized_pnl_total: Decimal
    open_risk: Decimal  # Σ risk_amount de órdenes PENDING_FILL/OPEN
    daily_loss_limit_reached: bool
    orders: list[PaperOrderSchema]
    warnings: list[str] = []

    @model_validator(mode="after")
    def _importes_validos(self) -> Self:
        if not self.open_risk.is_finite() or self.open_risk < 0:
            raise ValueError(
                f"open_risk debe ser un decimal finito >= 0 (recibido {self.open_risk})"
            )
        return self


class PaperRefreshResult(BaseModel):
    """Resultado de `POST /paper/refresh`."""

    model_config = _PAPER_CONFIG

    orders_checked: int
    orders_filled: int
    orders_closed: int
    warnings: list[str] = []

    @model_validator(mode="after")
    def _contadores_coherentes(self) -> Self:
        for nombre in ("orders_checked", "orders_filled", "orders_closed"):
            valor: int = getattr(self, nombre)
            if valor < 0:
                raise ValueError(f"{nombre} no puede ser negativo (recibido {valor})")
        return self
