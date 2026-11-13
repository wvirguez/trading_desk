"""Position sizing exacto en Decimal (D52, D60).

Limitaciones asumidas (D60): la cuenta está en USD y los 4 instrumentos del MVP cotizan en
USD/USDT, por lo que el valor de punto es 1 (pérdida = unidades x distancia de precio).
Otra divisa de cuenta o de cotización exigiría una conversión que está fuera de alcance.

Modo "por debajo del lote": si ``units < lot_size`` el resultado devuelve ``units == 0`` (con
``risk_amount``, ``risk_pct`` y ``notional`` a 0). Quien llama (guardas, 4F) debe tratar
``units == 0`` como veto ``SIZE_BELOW_LOT``; esta función no emite vetos.
"""

from decimal import Decimal, localcontext

from app.schemas.instrument import InstrumentSchema
from app.schemas.risk import PositionSizeResult

_PRECISION = 60
_HUNDRED = Decimal(100)


def _validate(equity: Decimal, risk_pct: Decimal, entry: Decimal, stop: Decimal) -> None:
    if not equity.is_finite() or equity <= 0:
        raise ValueError(f"El capital debe ser mayor que 0 (recibido: {equity})")
    if not risk_pct.is_finite() or risk_pct <= 0:
        raise ValueError(f"El riesgo por operación debe ser mayor que 0 (recibido: {risk_pct})")
    if not entry.is_finite() or entry <= 0:
        raise ValueError(f"El precio de entrada debe ser mayor que 0 (recibido: {entry})")
    if not stop.is_finite() or stop <= 0:
        raise ValueError(f"El precio de stop debe ser mayor que 0 (recibido: {stop})")
    if entry == stop:
        raise ValueError(f"La entrada y el stop coinciden ({entry}); la distancia al stop es 0")


def position_size(
    equity: Decimal,
    risk_pct: Decimal,
    entry: Decimal,
    stop: Decimal,
    instrument: InstrumentSchema,
) -> PositionSizeResult:
    """Calcula el tamaño de posición (D60).

    ``risk_pct`` va en unidades de porcentaje, como ``Settings`` (1.0 = 1 %).

    - ``risk_amount = equity * risk_pct / 100``
    - ``distancia = |entry - stop|`` redondeada HACIA ARRIBA a múltiplo de ``tick_size``
    - ``units = risk_amount / distancia`` redondeado HACIA ABAJO a múltiplo de ``lot_size``

    Devuelve el riesgo real (``units * distancia``), que nunca supera el pedido. Sirve para
    largos y cortos (usa el valor absoluto). Lanza ``ValueError`` con entradas inválidas.
    """
    _validate(equity, risk_pct, entry, stop)
    tick = instrument.tick_size
    lot = instrument.lot_size
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        raw_distance = abs(entry - stop)
        ticks, rest = divmod(raw_distance, tick)
        if rest:
            ticks += 1
        distance = ticks * tick  # > 0 porque raw_distance > 0

        risk_target = equity * risk_pct / _HUNDRED
        lots, _ = divmod(risk_target, distance * lot)
        units = lots * lot

        if units < lot:
            return PositionSizeResult(
                units=Decimal(0),
                risk_amount=Decimal(0),
                risk_pct=Decimal(0),
                stop_distance=distance,
                notional=Decimal(0),
            )

        real_risk = units * distance
        ctx.rounding = "ROUND_FLOOR"  # el % real nunca se redondea al alza
        real_pct = real_risk / equity * _HUNDRED
        return PositionSizeResult(
            units=units,
            risk_amount=real_risk,
            risk_pct=real_pct,
            stop_distance=distance,
            notional=units * entry,
        )
