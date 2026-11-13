"""Estadísticos de régimen: z-score móvil, exponente de Hurst y p-valor de ADF.

Núcleo puro: solo numpy, polars y statsmodels (aislado en `adf_pvalue`).
"""

import math

import numpy as np
import polars as pl
from numpy.typing import ArrayLike, NDArray

MIN_OBS = 100
_HURST_LAGS = range(2, 21)


def zscore(series: pl.Series, window: int) -> pl.Series:
    """Z-score móvil causal: `z_t = (x_t - media_w) / std_w`.

    La media y la desviación típica muestral (ddof=1) se calculan sobre las `window`
    observaciones `x_{t-window+1..t}` (solo datos <= t). Es null si la ventana no
    está completa o si `std = 0` (serie constante).
    """
    if window < 2:
        raise ValueError("window debe ser mayor o igual que 2")
    x = series.cast(pl.Float64)
    mean = x.rolling_mean(window_size=window, min_samples=window)
    std = x.rolling_std(window_size=window, min_samples=window, ddof=1)
    z = (x - mean) / std
    # Ventana constante (máx == mín) -> std = 0 -> null; evita ruido de redondeo.
    span = x.rolling_max(window_size=window, min_samples=window) - x.rolling_min(
        window_size=window, min_samples=window
    )
    return pl.select(pl.when(span > 0).then(z).otherwise(None)).to_series()


def _clean(x: ArrayLike, min_obs: int) -> NDArray[np.float64] | None:
    arr = np.asarray(x, dtype=np.float64)
    if arr.ndim != 1 or arr.size < min_obs or not np.all(np.isfinite(arr)):
        return None
    if np.ptp(arr) == 0.0:
        return None
    return arr


def hurst_exponent(x: ArrayLike, min_obs: int = MIN_OBS) -> float:
    """Exponente de Hurst por varianza de incrementos (D53).

    `H` es la pendiente de la regresión log-log `ln std(x_{t+tau} - x_t) ~ H ln tau`
    para `tau = 2..20`, sobre la serie de niveles. `H ~ 0.5` paseo aleatorio,
    `H < 0.5` reversión a la media, `H > 0.5` persistencia. Devuelve `nan` si hay
    menos de `min_obs` datos o la serie es constante.
    """
    arr = _clean(x, min_obs)
    if arr is None:
        return float("nan")
    lags = np.array(list(_HURST_LAGS), dtype=np.float64)
    stds = np.array([np.std(arr[int(lag) :] - arr[: -int(lag)]) for lag in lags])
    if np.any(stds <= 0.0):
        return float("nan")
    slope = np.polyfit(np.log(lags), np.log(stds), 1)[0]
    return float(slope)


def adf_pvalue(x: ArrayLike, min_obs: int = MIN_OBS) -> float:
    """P-valor del contraste de Dickey-Fuller aumentado (H0: raíz unitaria).

    `adfuller(x, regression="c", autolag="AIC")`. Un p-valor bajo (< alfa) rechaza la
    raíz unitaria, es decir, sugiere estacionariedad. Devuelve `nan` si hay menos de
    `min_obs` datos o la serie es constante.
    """
    arr = _clean(x, min_obs)
    if arr is None:
        return float("nan")
    from statsmodels.tsa.stattools import adfuller

    try:
        p = float(adfuller(arr, regression="c", autolag="AIC", result_object=False)[1])
    except ValueError:
        return float("nan")
    return p if math.isfinite(p) else float("nan")
