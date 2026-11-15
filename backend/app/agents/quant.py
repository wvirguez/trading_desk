"""Agente cuantitativo (3.5): régimen, playbook y Kelly informativo; cifras solo de herramientas.

Las herramientas son envoltorios finos sobre las funciones puras de `app.quant` y `app.risk`
(D86). El validador recalcula `classify_regime` sobre los cierres del marco del informe y
rechaza (`ModelRetry`) un régimen o unos `stats` distintos.

Decisiones:
- Un playbook que contradice el régimen (p. ej. `MEAN_REVERSION` con `TRENDING`) se ACEPTA, pero
  el validador exige que `reasoning` contenga `CONTRA_REGIMEN_MARK`; así queda anotado en el
  propio informe y lo veta, si procede, la propuesta o el auditor.
- `kelly` solo puede salir de la herramienta `kelly(p, b)`. Sus llamadas se registran en
  `AgentDeps.kelly_calls` (estado por ejecución, sin globales); el informe debe coincidir con
  alguna y declarar «sin calibrar» en `reasoning`.
"""

import math
from typing import Any

import polars as pl
from pydantic_ai import Agent, ModelRetry, RunContext

from app.agents.deps import AgentDeps
from app.agents.prompts import QUANT_PROMPT
from app.quant.features import atr, log_returns, rolling_volatility
from app.quant.regime import classify_regime
from app.quant.regime_stats import adf_pvalue, hurst_exponent, zscore
from app.risk.kelly import kelly_fraction
from app.schemas.agents import QuantAlphaReport
from app.schemas.enums import Playbook, RegimeLabel, Timeframe
from app.schemas.quant import RegimeReport, RegimeStats

CONTRA_REGIMEN_MARK = "contra el régimen"
UNCALIBRATED_MARK = "sin calibrar"
_REL_TOL = 1e-9

quant_agent: Agent[AgentDeps, QuantAlphaReport] = Agent(
    output_type=QuantAlphaReport,
    deps_type=AgentDeps,
    system_prompt=QUANT_PROMPT,
    retries=2,
    name="quant",
)


def _available(deps: AgentDeps) -> str:
    return ", ".join(sorted(tf.value for tf in deps.candles))


def _frame(deps: AgentDeps, timeframe: Timeframe) -> pl.DataFrame:
    df = deps.candles.get(timeframe)
    if df is None:
        raise ModelRetry(
            f"El marco {timeframe.value} no está disponible; marcos disponibles: "
            f"{_available(deps)}."
        )
    return df


def _last(value: Any) -> float | None:
    return None if value is None else float(value)


def _regime(deps: AgentDeps, timeframe: Timeframe) -> RegimeReport:
    close = _frame(deps, timeframe)["close"]
    try:
        return classify_regime(close)
    except ValueError as exc:
        raise ModelRetry(f"Marco {timeframe.value}: {exc}") from exc


@quant_agent.tool
def get_features(
    ctx: RunContext[AgentDeps], timeframe: Timeframe, vol_window: int = 20, atr_period: int = 14
) -> dict[str, Any]:
    """Último rendimiento logarítmico, volatilidad móvil y ATR del marco (null si no hay)."""
    df = _frame(ctx.deps, timeframe)
    try:
        row = df.select(r=log_returns(), v=rolling_volatility(vol_window), a=atr(atr_period)).tail(
            1
        )
    except ValueError as exc:
        raise ModelRetry(str(exc)) from exc
    return {
        "timeframe": timeframe.value,
        "n_obs": df.height,
        "vol_window": vol_window,
        "atr_period": atr_period,
        "log_return": _last(row["r"][0]),
        "volatility": _last(row["v"][0]),
        "atr": _last(row["a"][0]),
    }


@quant_agent.tool
def get_regime_stats(
    ctx: RunContext[AgentDeps], timeframe: Timeframe, zscore_window: int = 50
) -> dict[str, Any]:
    """Hurst, p-valor ADF y último z-score de los cierres del marco (nan si no hay datos)."""
    close = _frame(ctx.deps, timeframe)["close"]
    try:
        z = zscore(close, zscore_window).tail(1)[0]
    except ValueError as exc:
        raise ModelRetry(str(exc)) from exc
    return {
        "timeframe": timeframe.value,
        "n_obs": len(close),
        "zscore_window": zscore_window,
        "hurst": hurst_exponent(close.to_numpy()),
        "adf_pvalue": adf_pvalue(close.to_numpy()),
        "zscore": float("nan") if z is None else float(z),
    }


@quant_agent.tool
def classify(ctx: RunContext[AgentDeps], timeframe: Timeframe) -> dict[str, Any]:
    """Régimen (`label`), `stats` y umbrales de `classify_regime` sobre los cierres del marco."""
    return _regime(ctx.deps, timeframe).model_dump(mode="json")


@quant_agent.tool
def kelly(ctx: RunContext[AgentDeps], p: float, b: float) -> dict[str, Any]:
    """Kelly fraccional INFORMATIVO (fracciones del capital, no %) para `p` y `b` hipotéticos."""
    settings = ctx.deps.settings
    try:
        result = kelly_fraction(
            p,
            b,
            fraction=float(settings.kelly_fraction),
            cap=float(settings.risk_per_trade_pct) / 100.0,
        )
    except ValueError as exc:
        raise ModelRetry(str(exc)) from exc
    ctx.deps.kelly_calls.append((p, b, result))
    return {
        "p": p,
        "b": b,
        "kelly": result.model_dump(mode="json"),
        "informativo": True,
        "calibrado": False,
        "aviso": "p y b son una hipótesis sin calibrar; Kelly no determina el tamaño.",
    }


def _same(a: float, b: float) -> bool:
    if math.isnan(a) or math.isnan(b):
        return math.isnan(a) and math.isnan(b)
    return math.isclose(a, b, rel_tol=_REL_TOL, abs_tol=0.0)


def _stats_equal(a: RegimeStats, b: RegimeStats) -> bool:
    return (
        a.n_obs == b.n_obs
        and _same(a.hurst, b.hurst)
        and _same(a.adf_pvalue, b.adf_pvalue)
        and _same(a.zscore, b.zscore)
        and _same(a.volatility_ratio, b.volatility_ratio)
    )


def _against_regime(playbook: Playbook, label: RegimeLabel) -> bool:
    return (playbook is Playbook.MEAN_REVERSION and label is RegimeLabel.TRENDING) or (
        playbook is Playbook.TREND_FOLLOWING and label is RegimeLabel.MEAN_REVERTING
    )


@quant_agent.output_validator
def validate_report(ctx: RunContext[AgentDeps], report: QuantAlphaReport) -> QuantAlphaReport:
    deps = ctx.deps
    if report.symbol != deps.instrument.symbol:
        raise ModelRetry(f"symbol debe ser {deps.instrument.symbol!r}, no {report.symbol!r}.")
    if report.timeframe not in deps.candles:
        raise ModelRetry(
            f"timeframe {report.timeframe.value} no está entre los marcos disponibles: "
            f"{_available(deps)}."
        )

    truth = _regime(deps, report.timeframe)
    if report.regime is not truth.label:
        raise ModelRetry(
            f"regime {report.regime.value} no coincide con classify({report.timeframe.value}): "
            f"{truth.label.value}. Copia el régimen devuelto por la herramienta."
        )
    if not _stats_equal(report.stats, truth.stats):
        raise ModelRetry(
            f"stats no coincide con classify({report.timeframe.value}): "
            f"{truth.stats.model_dump(mode='json')}. Copia los estadísticos tal cual."
        )

    if _against_regime(report.playbook, truth.label) and (
        CONTRA_REGIMEN_MARK not in report.reasoning.lower()
    ):
        raise ModelRetry(
            f"El playbook {report.playbook.value} contradice el régimen {truth.label.value}: se "
            f"permite, pero `reasoning` debe anotarlo con la expresión «{CONTRA_REGIMEN_MARK}» "
            "y justificarlo; también puedes elegir un playbook coherente o NO_TRADE."
        )

    if report.kelly is not None:
        if not deps.kelly_calls:
            raise ModelRetry(
                "kelly solo puede provenir de la herramienta kelly(p, b); no la llamaste. "
                "Llámala o deja kelly en null."
            )
        if not any(report.kelly == res for _, _, res in deps.kelly_calls):
            calls = "; ".join(
                f"p={p}, b={b} -> {res.model_dump(mode='json')}" for p, b, res in deps.kelly_calls
            )
            raise ModelRetry(
                f"kelly no coincide con ninguna llamada a la herramienta ({calls}). Copia el "
                "resultado de la herramienta sin modificarlo."
            )
        if UNCALIBRATED_MARK not in report.reasoning.lower():
            raise ModelRetry(
                "Kelly es informativo: `reasoning` debe indicar que p y b están "
                f"«{UNCALIBRATED_MARK}»."
            )
    return report
