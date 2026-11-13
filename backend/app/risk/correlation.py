"""Matriz de correlación entre símbolos (D63).

Se calcula sobre log-retornos de cierre, con las ÚLTIMAS ``window`` observaciones de retorno
comunes a ambos símbolos (unión interna por ``ts``). Las claves del diccionario son pares
ordenados alfabéticamente ``(a, b)`` con ``a < b``; para consultar en cualquier orden usa
``pair_correlation``. Devuelve ``nan`` si hay menos de ``MIN_OBSERVATIONS`` observaciones
comunes o si alguna serie es constante; las guardas (``guards.py``) tratan ``nan`` como 1.0.
"""

import math
from itertools import combinations

import numpy as np
import polars as pl

MIN_OBSERVATIONS = 20


def _log_returns(df: pl.DataFrame) -> pl.DataFrame:
    return (
        df.select("ts", "close")
        .sort("ts")
        .select("ts", pl.col("close").log().diff().alias("ret"))
        .drop_nulls()
        .filter(pl.col("ret").is_finite())
    )


def correlation_matrix(
    closes: dict[str, pl.DataFrame], window: int
) -> dict[tuple[str, str], float]:
    """Correlación de Pearson de log-retornos para cada par ``(a, b)`` con ``a < b``."""
    returns = {symbol: _log_returns(df) for symbol, df in closes.items()}
    result: dict[tuple[str, str], float] = {}
    for a, b in combinations(sorted(returns), 2):
        joined = (
            returns[a]
            .join(returns[b], on="ts", how="inner", suffix="_b")
            .sort("ts")
            .tail(max(window, 0))
        )
        if joined.height < MIN_OBSERVATIONS:
            result[(a, b)] = math.nan
            continue
        x = joined["ret"].to_numpy()
        y = joined["ret_b"].to_numpy()
        if np.ptp(x) == 0.0 or np.ptp(y) == 0.0:
            result[(a, b)] = math.nan
            continue
        rho = float(np.corrcoef(x, y)[0, 1])
        result[(a, b)] = max(-1.0, min(1.0, rho)) if math.isfinite(rho) else math.nan
    return result


def pair_correlation(matrix: dict[tuple[str, str], float], a: str, b: str) -> float:
    """Correlación del par en cualquier orden; ``nan`` si no existe (o si ``a == b`` ausente)."""
    key = (a, b) if a < b else (b, a)
    return matrix.get(key, math.nan)
