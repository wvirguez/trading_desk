"""Construcción determinista de la señal propuesta (D93). Función pura, todo en Decimal.

El LLM decide el sesgo, el *playbook* y la zona; aquí se calculan todas las cifras (D86).

Reglas
------
- Dirección:
  - ``TREND_FOLLOWING`` sigue ``structure.htf_alignment`` (BULLISH -> LONG, BEARISH -> SHORT).
  - ``MEAN_REVERSION`` va contra la desviación: ``zscore > 0`` -> SHORT, ``zscore < 0`` -> LONG.
  - ``NO_TRADE`` -> sin propuesta.
- Entrada: borde cercano de la zona FVG elegida (``structure.zone_ts``) si existe, está sin
  mitigar y apunta en el sentido de la operación (LONG: ``high`` de un FVG alcista; SHORT:
  ``low`` de uno bajista). Si no, último cierre. Se redondea al tick más cercano.
- SL: ``invalidation_level`` -/+ ``sl_atr_buffer * atr``, redondeado al tick EN CONTRA de la
  operación (LONG hacia abajo, SHORT hacia arriba).
- TP: ``entrada +/- target_rr * distancia``, redondeado al tick ALEJÁNDOSE de la entrada (LONG
  hacia arriba), de modo que el R:R real nunca baja de ``target_rr``. ``rr`` se publica truncado
  a 4 decimales (nunca por encima del real).

Ambigüedades y su resolución (nada se inventa; ante la duda, sin propuesta con motivo)
---------------------------------------------------------------------------------------
- Falta ``invalidation_level`` o está del lado equivocado de la entrada (LONG: >= entrada; SHORT:
  <= entrada): sin propuesta. No se deduce un nivel alternativo.
- ``MEAN_REVERSION`` con sesgo HTF contrario a la dirección de la reversión (p. ej. z > 0 pero
  sesgo alcista): sesgos incompatibles, sin propuesta. Con sesgo NEUTRAL sí se permite.
  ``TREND_FOLLOWING`` con sesgo NEUTRAL: sin propuesta.
- ``zscore`` exactamente 0 (o no finito) en ``MEAN_REVERSION``: sin dirección, sin propuesta.
- ``zone_ts`` ausente, sin FVG coincidente en ``fvgs``, mitigado, de sentido contrario, o con el
  borde en el lado equivocado del último cierre: se usa el último cierre (se anota en ``source``).
- ATR igual a 0 o SL resultante <= 0 o distancia al SL nula: sin propuesta.
- Entradas incoherentes (símbolo/timeframe distintos, precios o ATR negativos o no finitos):
  ``ValueError``, porque son errores de programación y no un "no operar".

``fvgs`` es un añadido a la firma del plan: ``MarketStructureReport`` solo trae ``zone_ts`` y los
bordes y la mitigación del FVG viven en ``MarketStructureResult.fvgs`` (herramienta de estructura).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_EVEN, Decimal, localcontext

from app.schemas.agents import MarketStructureReport, QuantAlphaReport
from app.schemas.enums import Bias, Direction, Playbook
from app.schemas.instrument import InstrumentSchema
from app.schemas.quant import FairValueGap
from app.schemas.signals import ProposedSignal

_PRECISION = 60
_RR_QUANTUM = Decimal("0.0001")


@dataclass(frozen=True)
class ProposalParams:
    """Parámetros de la propuesta (``PROPOSAL_TARGET_RR`` y ``PROPOSAL_SL_ATR_BUFFER``)."""

    target_rr: Decimal
    sl_atr_buffer: Decimal

    def __post_init__(self) -> None:
        if not self.target_rr.is_finite() or self.target_rr <= 0:
            raise ValueError(f"target_rr debe ser un decimal finito mayor que 0 ({self.target_rr})")
        if not self.sl_atr_buffer.is_finite() or self.sl_atr_buffer < 0:
            raise ValueError(
                f"sl_atr_buffer debe ser un decimal finito no negativo ({self.sl_atr_buffer})"
            )


@dataclass(frozen=True)
class NoTradeReason:
    """Resultado "no operar": motivo en español, sin propuesta."""

    reason: str


def _round_tick(value: Decimal, tick: Decimal, mode: str) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        return (value / tick).to_integral_value(rounding=mode) * tick


def _direction(
    structure: MarketStructureReport, quant: QuantAlphaReport
) -> Direction | NoTradeReason:
    bias = structure.htf_alignment
    if quant.playbook is Playbook.NO_TRADE:
        return NoTradeReason("El playbook es NO_TRADE: no se propone operación.")
    if quant.playbook is Playbook.TREND_FOLLOWING:
        if bias is Bias.BULLISH:
            return Direction.LONG
        if bias is Bias.BEARISH:
            return Direction.SHORT
        return NoTradeReason("TREND_FOLLOWING con sesgo HTF neutral: no hay dirección que seguir.")
    z = quant.stats.zscore
    if not z == z or z in (float("inf"), float("-inf")) or z == 0.0:
        return NoTradeReason(
            "MEAN_REVERSION sin desviación del z-score utilizable (cero o no finita)."
        )
    direction = Direction.SHORT if z > 0 else Direction.LONG
    contrario = Bias.BULLISH if direction is Direction.SHORT else Bias.BEARISH
    if bias is contrario:
        return NoTradeReason(
            f"Sesgos incompatibles: MEAN_REVERSION con z-score {z:.2f} implica {direction.value}, "
            f"pero el sesgo HTF es {bias.value}."
        )
    return direction


def _entry(
    structure: MarketStructureReport,
    direction: Direction,
    last_close: Decimal,
    fvgs: Sequence[FairValueGap],
) -> tuple[Decimal, str]:
    nota = "entrada = último cierre"
    if structure.zone_ts is None:
        return last_close, f"{nota} (sin zona FVG elegida)"
    zona = next((f for f in fvgs if f.ts == structure.zone_ts), None)
    if zona is None:
        return last_close, f"{nota} (la zona elegida no figura en los FVG)"
    if zona.mitigated_at is not None:
        return last_close, f"{nota} (el FVG elegido ya está mitigado)"
    if zona.direction is not direction:
        return last_close, f"{nota} (el FVG elegido es de sentido contrario)"
    borde = zona.high if direction is Direction.LONG else zona.low
    if (direction is Direction.LONG and borde > last_close) or (
        direction is Direction.SHORT and borde < last_close
    ):
        return last_close, f"{nota} (el borde del FVG queda del lado equivocado del precio)"
    return borde, f"entrada = borde cercano del FVG {zona.ts.isoformat()}"


def build_proposal(
    structure: MarketStructureReport,
    quant: QuantAlphaReport,
    last_close: Decimal,
    atr: Decimal,
    instrument: InstrumentSchema,
    params: ProposalParams,
    fvgs: Sequence[FairValueGap] = (),
) -> ProposedSignal | NoTradeReason:
    """Construye la propuesta determinista o explica por qué no hay (ver docstring del módulo)."""
    if not (structure.symbol == quant.symbol == instrument.symbol):
        raise ValueError(
            f"El símbolo no coincide: estructura={structure.symbol}, quant={quant.symbol}, "
            f"instrumento={instrument.symbol}"
        )
    if structure.entry_timeframe is not quant.timeframe:
        raise ValueError(
            f"El timeframe no coincide: estructura={structure.entry_timeframe.value}, "
            f"quant={quant.timeframe.value}"
        )
    if not last_close.is_finite() or last_close <= 0:
        raise ValueError(f"El último cierre debe ser un decimal finito mayor que 0 ({last_close})")
    if not atr.is_finite() or atr < 0:
        raise ValueError(f"El ATR debe ser un decimal finito no negativo ({atr})")

    direction = _direction(structure, quant)
    if isinstance(direction, NoTradeReason):
        return direction
    if atr == 0:
        return NoTradeReason("El ATR es 0: no hay volatilidad medible para colocar el stop.")
    inval = structure.invalidation_level
    if inval is None:
        return NoTradeReason("Falta el nivel de invalidación: no se inventa un stop.")

    tick = instrument.tick_size
    largo = direction is Direction.LONG
    raw_entry, entry_note = _entry(structure, direction, last_close, fvgs)
    entry = _round_tick(raw_entry, tick, ROUND_HALF_EVEN)
    if entry <= 0:
        return NoTradeReason(f"La entrada redondeada al tick no es positiva ({entry}).")
    if (largo and inval >= entry) or (not largo and inval <= entry):
        return NoTradeReason(
            f"El nivel de invalidación {inval} está del lado equivocado de la entrada {entry} "
            f"para una operación {direction.value}."
        )

    with localcontext() as ctx:
        ctx.prec = _PRECISION
        colchon = params.sl_atr_buffer * atr
        raw_sl = inval - colchon if largo else inval + colchon
        sl = _round_tick(raw_sl, tick, ROUND_FLOOR if largo else ROUND_CEILING)
        if sl <= 0:
            return NoTradeReason(f"El stop calculado no es positivo ({sl}).")
        distancia = abs(entry - sl)
        if distancia == 0:
            return NoTradeReason("La distancia al stop es 0 tras el redondeo al tick.")
        raw_tp = (
            entry + params.target_rr * distancia if largo else entry - params.target_rr * distancia
        )
        tp = _round_tick(raw_tp, tick, ROUND_CEILING if largo else ROUND_FLOOR)
        if tp <= 0:
            return NoTradeReason(f"El objetivo calculado no es positivo ({tp}).")
        rr = (abs(tp - entry) / distancia).quantize(_RR_QUANTUM, rounding=ROUND_DOWN)

    source = (
        f"{entry_note}; stop = invalidación {inval} {'-' if largo else '+'} "
        f"{params.sl_atr_buffer}·ATR({atr}) redondeado al tick en contra = {sl}; "
        f"objetivo = entrada {'+' if largo else '-'} {params.target_rr}·{distancia} "
        f"redondeado al tick = {tp}"
    )
    return ProposedSignal(
        symbol=instrument.symbol,
        timeframe=structure.entry_timeframe,
        direction=direction,
        entry=entry,
        stop_loss=sl,
        take_profit=tp,
        rr=rr,
        source=source,
    )
