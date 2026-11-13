"""Backtester vectorizado de la estrategia de referencia (reversión a la media por z-score).

Núcleo puro (solo numpy y polars). Decisiones: D56 (estrategia), D57 (ejecución sin
anticipación), D58 (métricas), D59 (redondeo a 10 decimales) y D64 (`config_hash`).

Estrategia (sobre el z-score causal de `close`, ventana `zscore_window`):

* larga: entra si `z <= -entry_z`; sale cuando `z >= -exit_z`;
* corta (solo si `allow_short`): entra si `z >= +entry_z`; sale cuando `z <= +exit_z`;
* con `exit_z = 0` la salida es el cruce por cero (la media móvil).

Estado sin bucle por vela: cada lado es una máquina con histéresis independiente. Se
marca `1` en las velas de entrada, `0` en las de salida y `null` en el resto, y un
`forward_fill` propaga la última marca (el estado). Las zonas de entrada y de salida de un
lado son disjuntas (`exit_z < entry_z`), de modo que la marca es no ambigua; además un
lado largo activo implica `z < -exit_z <= exit_z`, con lo que el corto está plano (y
viceversa): nunca coinciden y `position = largo - corto` en {-1, 0, +1}. Un salto directo
de corto a largo (o al revés) produce la salida de un lado y la entrada del otro en la
misma vela. Un `z` nulo (ventana incompleta o constante) no genera marca: se mantiene el
estado previo (plano al inicio).

Ejecución (D57): la posición decidida con el cierre de `t` se aplica al retorno de
`t -> t+1` (`position.shift(1)`). Retorno de la barra: `r_t = pos_{t-1} * (exp(lr_t) - 1)`
con `lr_t = ln(close_t / close_{t-1})` (retorno simple del activo; en cortos cambia de
signo). Capital: `equity_t = initial_capital * prod_{k<=t}(1 + r_k)`. Sin costes, sin
*slippage*, sin stops: un corto con subida > 100 % en una barra daría equity negativa.
"""

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

import numpy as np
import polars as pl
from numpy.typing import NDArray

from app.quant.regime_stats import zscore
from app.schemas.enums import SessionType, Timeframe
from app.schemas.quant import BacktestConfig, BacktestMetricsSchema, EquityPoint

_DECIMALS = 10


@dataclass(frozen=True)
class BacktestResult:
    """Resultado interno del backtest (floats y numpy; sin redondear)."""

    ts: tuple[datetime, ...]
    equity: NDArray[np.float64]
    position: NDArray[np.float64]  # posición aplicada a cada barra (ya con shift(1))
    n_bars: int
    n_trades: int
    initial_capital: float
    total_return: float
    sharpe: float
    max_drawdown: float
    win_rate: float
    expectancy: float
    trade_returns: NDArray[np.float64]


def periods_per_year(timeframe: Timeframe, session: SessionType) -> int:
    """Periodos por año (D58): cripto 365 días; el resto 252 días; por las velas de cada día."""
    bars_per_day = 86400 // int(timeframe.duration.total_seconds())
    days = 365 if session is SessionType.CRYPTO_24_7 else 252
    return days * bars_per_day


def _hysteresis(z: pl.Series, enter: pl.Expr, leave: pl.Expr, enabled: bool) -> pl.Series:
    """Estado 0/1 de un lado por marcas de entrada/salida + `forward_fill`."""
    if not enabled:
        return pl.Series("state", np.zeros(len(z)), dtype=pl.Float64)
    frame = pl.DataFrame({"z": z})
    mark = pl.when(enter).then(1.0).when(leave).then(0.0).otherwise(None)
    return frame.select(mark.forward_fill().fill_null(0.0).alias("state")).to_series()


def _positions(z: pl.Series, config: BacktestConfig) -> NDArray[np.float64]:
    """Posición decidida con el cierre de cada vela, en {-1, 0, +1}."""
    zc = pl.col("z")
    long_state = _hysteresis(z, zc <= -config.entry_z, zc >= -config.exit_z, True)
    short_state = _hysteresis(z, zc >= config.entry_z, zc <= config.exit_z, config.allow_short)
    return (long_state - short_state).to_numpy().astype(np.float64)


def _trade_returns(applied: NDArray[np.float64], r: NDArray[np.float64]) -> NDArray[np.float64]:
    """Rendimiento de cada operación: tramo continuo con la misma posición `!= 0`."""
    if applied.size == 0:
        return np.empty(0, dtype=np.float64)
    changes = np.concatenate(([True], applied[1:] != applied[:-1]))
    segment = np.cumsum(changes)
    frame = pl.DataFrame({"seg": segment, "pos": applied, "g": 1.0 + r})
    out = (
        frame.filter(pl.col("pos") != 0.0)
        .group_by("seg", maintain_order=True)
        .agg(pl.col("g").product())
    )
    return (out["g"] - 1.0).to_numpy().astype(np.float64)


def run_backtest(df: pl.DataFrame, config: BacktestConfig, periods_per_year: int) -> BacktestResult:
    """Ejecuta la estrategia de referencia sobre `df` (columnas `ts`, `close`)."""
    n = df.height
    if n < 2:
        raise ValueError("Se necesitan al menos 2 velas para un backtest")
    close = df["close"].cast(pl.Float64)
    z = zscore(close, config.zscore_window)
    decided = _positions(z, config)
    applied = np.concatenate(([0.0], decided[:-1]))  # shift(1), D57

    log_ret = np.log(close.to_numpy().astype(np.float64))
    log_ret = np.concatenate(([0.0], np.diff(log_ret)))
    r = applied * np.expm1(log_ret)
    initial = float(config.initial_capital)
    equity = initial * np.cumprod(1.0 + r)

    total_return = float(equity[-1] / initial - 1.0)
    if np.ptp(r) == 0.0:
        sharpe = 0.0
    else:
        sharpe = float(np.mean(r) / np.std(r, ddof=1) * math.sqrt(periods_per_year))
    peak = np.maximum.accumulate(np.concatenate(([initial], equity)))[1:]
    max_dd = min(0.0, float(np.min(equity / peak - 1.0)))

    trades = _trade_returns(applied, r)
    n_trades = int(trades.size)
    win_rate = float(np.mean(trades > 0.0)) if n_trades else 0.0
    expectancy = float(np.mean(trades)) if n_trades else 0.0
    return BacktestResult(
        ts=tuple(df["ts"].to_list()),
        equity=equity,
        position=applied,
        n_bars=n,
        n_trades=n_trades,
        initial_capital=initial,
        total_return=total_return,
        sharpe=sharpe,
        max_drawdown=max_dd,
        win_rate=win_rate,
        expectancy=expectancy,
        trade_returns=trades,
    )


def _dec(x: float) -> Decimal:
    return Decimal(str(round(x, _DECIMALS)))


def to_metrics_schema(
    result: BacktestResult,
    config: BacktestConfig,
    strategy_id: UUID,
    warnings: list[str],
) -> BacktestMetricsSchema:
    """Frontera del esquema: floats a 10 decimales, dinero en `Decimal` (D52, D59)."""
    return BacktestMetricsSchema(
        strategy_id=strategy_id,
        config=config,
        n_bars=result.n_bars,
        n_trades=result.n_trades,
        total_return=round(result.total_return, _DECIMALS),
        sharpe=round(result.sharpe, _DECIMALS),
        max_drawdown=round(result.max_drawdown, _DECIMALS),
        win_rate=round(result.win_rate, _DECIMALS),
        expectancy=round(result.expectancy, _DECIMALS),
        final_equity=_dec(float(result.equity[-1])),
        equity_curve=[
            EquityPoint(ts=ts, equity=_dec(float(e)))
            for ts, e in zip(result.ts, result.equity, strict=True)
        ],
        warnings=list(warnings),
    )


def config_hash(config: BacktestConfig, data_from: datetime, data_to: datetime) -> str:
    """SHA-256 del JSON canónico (claves ordenadas) de la configuración y el rango (D64)."""
    params = config.model_dump(mode="json")
    params["initial_capital"] = format(config.initial_capital.normalize(), "f")
    payload = {
        "params": params,
        "data_from": data_from.isoformat(),
        "data_to": data_to.isoformat(),
    }
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
