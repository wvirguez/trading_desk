"""Agente de estructura de mercado (3.4): sesgo y zona FVG, con cifras solo de las herramientas.

Las herramientas son envoltorios finos sobre `analyze_structure` (D86). `analyze_structure` es
una función pura y determinista, así que el validador la recalcula por marco y obtiene
exactamente lo que vio el modelo, sin estado global ni caché compartida.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic_ai import Agent, ModelRetry, RunContext

from app.agents.deps import AgentDeps
from app.agents.prompts import STRUCTURE_PROMPT
from app.quant.structure import analyze_structure
from app.schemas.agents import MarketStructureReport
from app.schemas.enums import Bias, Timeframe
from app.schemas.quant import MarketStructureResult

structure_agent: Agent[AgentDeps, MarketStructureReport] = Agent(
    output_type=MarketStructureReport,
    deps_type=AgentDeps,
    system_prompt=STRUCTURE_PROMPT,
    retries=2,
    name="structure",
)


def _available(deps: AgentDeps) -> str:
    return ", ".join(sorted(tf.value for tf in deps.candles))


def _structure(deps: AgentDeps, timeframe: Timeframe) -> MarketStructureResult:
    df = deps.candles.get(timeframe)
    if df is None:
        raise ModelRetry(
            f"El marco {timeframe.value} no está disponible; marcos disponibles: "
            f"{_available(deps)}."
        )
    return analyze_structure(df)


def _price_levels(res: MarketStructureResult) -> set[Decimal]:
    levels = {s.price for s in res.swings}
    levels |= {e.level for e in res.events}
    for f in res.fvgs:
        levels |= {f.low, f.high}
    return levels


@structure_agent.tool
def get_structure(ctx: RunContext[AgentDeps], timeframe: Timeframe) -> dict[str, Any]:
    """Swings, eventos BOS/CHOCH y FVG del marco (precios como cadenas decimales)."""
    return _structure(ctx.deps, timeframe).model_dump(mode="json")


@structure_agent.tool
def get_last_close(ctx: RunContext[AgentDeps], timeframe: Timeframe) -> dict[str, str]:
    """Último cierre del marco (cadena decimal) y la marca de tiempo de su vela."""
    df = ctx.deps.candles.get(timeframe)
    if df is None or df.height == 0:
        raise ModelRetry(
            f"El marco {timeframe.value} no tiene velas; marcos disponibles: "
            f"{_available(ctx.deps)}."
        )
    ts: datetime = df["ts"][-1]
    return {
        "timeframe": timeframe.value,
        "ts": ts.isoformat(),
        "close": str(Decimal(repr(df["close"][-1]))),
    }


def _check_last_events(
    report: MarketStructureReport, results: dict[Timeframe, MarketStructureResult]
) -> None:
    """`last_event` declarado = tipo del último evento que devuelve la herramienta del marco.

    Regla (D111): solo se rechaza una afirmación falsa. `None` siempre es aceptable (el modelo
    no declara evento); un valor no nulo debe coincidir con `events[-1].type` del marco.
    """
    for item in report.timeframes:
        if item.last_event is None:
            continue
        events = results[item.timeframe].events
        actual = events[-1].type if events else None
        if item.last_event is not actual:
            shown = actual.value if actual is not None else "ninguno"
            raise ModelRetry(
                f"last_event {item.last_event.value} del marco {item.timeframe.value} no coincide "
                f"con el último evento de get_structure ({shown}); usa ese valor o null."
            )


def _check_htf_alignment(report: MarketStructureReport) -> None:
    """`htf_alignment` BULLISH/BEARISH no puede contradecir el sesgo de los marcos superiores.

    Regla (D111): se consideran los marcos citados cuya duración supera la del marco de entrada;
    si alguno tiene el sesgo opuesto, se rechaza. NEUTRAL siempre es aceptable, y sin marcos
    superiores citados (o con todos NEUTRAL) no hay nada que contradecir. El `bias` de cada marco
    sigue siendo una hipótesis del modelo: no se valida contra las herramientas.
    """
    if report.htf_alignment is Bias.NEUTRAL:
        return
    opposite = Bias.BEARISH if report.htf_alignment is Bias.BULLISH else Bias.BULLISH
    entry_duration = report.entry_timeframe.duration
    for item in report.timeframes:
        if item.timeframe.duration > entry_duration and item.bias is opposite:
            raise ModelRetry(
                f"htf_alignment {report.htf_alignment.value} contradice el sesgo {item.bias.value} "
                f"del marco superior {item.timeframe.value}; usa NEUTRAL o corrige el sesgo."
            )


@structure_agent.output_validator
def validate_report(
    ctx: RunContext[AgentDeps], report: MarketStructureReport
) -> MarketStructureReport:
    deps = ctx.deps
    if report.symbol != deps.instrument.symbol:
        raise ModelRetry(f"symbol debe ser {deps.instrument.symbol!r}, no {report.symbol!r}.")
    if report.entry_timeframe not in deps.candles:
        raise ModelRetry(
            f"entry_timeframe {report.entry_timeframe.value} no está entre los marcos "
            f"disponibles: {_available(deps)}."
        )

    results: dict[Timeframe, MarketStructureResult] = {}
    for item in report.timeframes:
        if item.timeframe not in deps.candles:
            raise ModelRetry(
                f"El marco {item.timeframe.value} no fue pedido; marcos disponibles: "
                f"{_available(deps)}."
            )
        res = results[item.timeframe] = _structure(deps, item.timeframe)
        valid_levels = _price_levels(res)
        for level in item.key_levels:
            if level not in valid_levels:
                raise ModelRetry(
                    f"El nivel {level} del marco {item.timeframe.value} no existe en la salida de "
                    "get_structure; usa solo precios devueltos por la herramienta."
                )
        open_ts = {f.ts for f in res.fvgs if f.mitigated_at is None}
        for ts in item.open_fvg_ts:
            if ts not in open_ts:
                raise ModelRetry(
                    f"El FVG {ts.isoformat()} del marco {item.timeframe.value} no existe o está "
                    "mitigado según get_structure; cita solo FVG con mitigated_at nulo."
                )

    entry_result = results[report.entry_timeframe] if report.entry_timeframe in results else None
    if entry_result is None:
        entry_result = _structure(deps, report.entry_timeframe)
    _check_last_events(report, results)
    _check_htf_alignment(report)
    if report.invalidation_level is not None:
        swing_prices = {s.price for s in entry_result.swings}  # todo swing está confirmado (D55)
        if report.invalidation_level not in swing_prices:
            raise ModelRetry(
                f"invalidation_level {report.invalidation_level} debe ser el precio de un swing "
                f"confirmado del marco de entrada {report.entry_timeframe.value} según "
                "get_structure (no un borde de FVG ni un nivel de otro marco)."
            )
    if report.zone_ts is not None:
        zone_frames = [results[report.entry_timeframe]] if report.entry_timeframe in results else []
        if not any(
            f.ts == report.zone_ts and f.mitigated_at is None for r in zone_frames for f in r.fvgs
        ):
            raise ModelRetry(
                f"zone_ts {report.zone_ts.isoformat()} no es un FVG no mitigado del marco de "
                f"entrada {report.entry_timeframe.value} (inclúyelo en `timeframes` y usa "
                "get_structure)."
            )
    return report
