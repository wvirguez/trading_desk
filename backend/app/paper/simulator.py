"""Simulador de fills de órdenes simuladas (D134). Función pura y determinista, en Decimal.

Reglas:
1. *Fill* al `open` de la primera vela del timeframe de la señal cuya apertura sea
   >= `executed_at`. Las velas anteriores a `executed_at` se ignoran.
2. Desde la vela de fill se evalúa vela a vela: LONG sale por SL si `low <= SL` y por TP si
   `high >= TP` (SHORT al revés).
3. Si SL y TP caben en la misma vela, gana SL (supuesto conservador).
4. Hueco: si el `open` de la vela ya está más allá del nivel (SL o TP), la salida es al `open`,
   no al nivel.
5. Vela de fill: el `open` es el fill. Decisión documentada: si ese `open` ya está más allá
   del SL (o del TP), la orden cierra en el propio fill, a ese precio (regla de hueco, caso
   «fill con la orden ya fuera de rango»); si no, se evalúan `low`/`high` de la vela.
6. PnL = +-(exit - fill) * units, en Decimal, sin redondeo (+ LONG; SHORT con el signo invertido).
7. Sin slippage, comisiones ni swap.

`closed_at` y `filled_at` son la apertura (`ts`) de la vela donde ocurre el evento: la
precisión temporal es la del timeframe. `last_processed_ts` es la apertura de la última vela
evaluada; el avance es incremental (solo se evalúan velas con `ts > last_processed_ts`), por
lo que reprocesar las mismas velas no cambia el estado. Si el riesgo real tras el fill
(`|fill - SL| * units`) supera `risk_amount` se emite un aviso (una sola vez, en el avance que
produce el fill); el tamaño no se recalcula.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.schemas.candle import CandleSchema
from app.schemas.enums import Direction, OrderStatus, Timeframe


@dataclass(frozen=True)
class OrderState:
    """Entrada del simulador: parámetros de la orden y su estado actual (sin ORM)."""

    direction: Direction
    units: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    risk_amount: Decimal
    executed_at: datetime
    timeframe: Timeframe
    status: OrderStatus = OrderStatus.PENDING_FILL
    fill_price: Decimal | None = None
    filled_at: datetime | None = None
    last_processed_ts: datetime | None = None


@dataclass(frozen=True)
class OrderAdvance:
    """Estado resultante de avanzar una orden. Coherente con `PaperOrderSchema`."""

    status: OrderStatus
    fill_price: Decimal | None
    filled_at: datetime | None
    exit_price: Decimal | None
    closed_at: datetime | None
    realized_pnl: Decimal | None
    last_processed_ts: datetime | None
    warnings: tuple[str, ...] = ()
    filled_now: bool = False
    closed_now: bool = False


def _unchanged(order: OrderState) -> OrderAdvance:
    return OrderAdvance(
        status=order.status,
        fill_price=order.fill_price,
        filled_at=order.filled_at,
        exit_price=None,
        closed_at=None,
        realized_pnl=None,
        last_processed_ts=order.last_processed_ts,
    )


def _exit_on_candle(order: OrderState, candle: CandleSchema) -> tuple[OrderStatus, Decimal] | None:
    """Salida en esta vela (SL antes que TP; hueco al `open`), o None si no toca niveles."""
    if order.direction is Direction.LONG:
        if candle.low <= order.stop_loss:
            return OrderStatus.CLOSED_SL, min(candle.open, order.stop_loss)
        if candle.high >= order.take_profit:
            return OrderStatus.CLOSED_TP, max(candle.open, order.take_profit)
    else:
        if candle.high >= order.stop_loss:
            return OrderStatus.CLOSED_SL, max(candle.open, order.stop_loss)
        if candle.low <= order.take_profit:
            return OrderStatus.CLOSED_TP, min(candle.open, order.take_profit)
    return None


def advance_order(order: OrderState, candles: Sequence[CandleSchema]) -> OrderAdvance:
    """Avanza una orden con las velas dadas (cualquier orden; se ordenan y deduplican)."""
    if order.status in (OrderStatus.CLOSED_TP, OrderStatus.CLOSED_SL):
        return _unchanged(order)
    for candle in candles:
        if candle.timeframe is not order.timeframe:
            raise ValueError(
                f"Vela {candle.ts.isoformat()} con timeframe {candle.timeframe.value}; "
                f"la orden usa {order.timeframe.value}"
            )
    if order.status is OrderStatus.OPEN and (order.fill_price is None or order.filled_at is None):
        raise ValueError("Una orden OPEN requiere fill_price y filled_at")

    floor = order.last_processed_ts
    if order.status is OrderStatus.OPEN and order.filled_at is not None:
        floor = max(floor, order.filled_at) if floor is not None else order.filled_at
    relevant = {
        c.ts: c for c in candles if c.ts >= order.executed_at and (floor is None or c.ts > floor)
    }

    status: OrderStatus = order.status
    fill_price = order.fill_price
    filled_at = order.filled_at
    last_ts = order.last_processed_ts
    warnings: list[str] = []
    filled_now = False
    exit_price: Decimal | None = None
    closed_at: datetime | None = None
    pnl: Decimal | None = None

    for ts in sorted(relevant):
        candle = relevant[ts]
        if status is OrderStatus.PENDING_FILL:
            status, fill_price, filled_at, filled_now = OrderStatus.OPEN, candle.open, ts, True
            risk = abs(candle.open - order.stop_loss) * order.units
            if risk > order.risk_amount:
                warnings.append(
                    f"El riesgo real tras el fill ({risk}) supera el riesgo de la señal "
                    f"({order.risk_amount}); el tamaño no se recalcula"
                )
        last_ts = ts
        assert fill_price is not None  # noqa: S101 - invariante: OPEN implica fill
        outcome = _exit_on_candle(order, candle)
        if outcome is not None:
            status, exit_price = outcome
            closed_at = ts
            if order.direction is Direction.LONG:
                pnl = (exit_price - fill_price) * order.units
            else:
                pnl = (fill_price - exit_price) * order.units
            break

    return OrderAdvance(
        status=status,
        fill_price=fill_price,
        filled_at=filled_at,
        exit_price=exit_price,
        closed_at=closed_at,
        realized_pnl=pnl,
        last_processed_ts=last_ts,
        warnings=tuple(warnings),
        filled_now=filled_now,
        closed_now=closed_at is not None,
    )
