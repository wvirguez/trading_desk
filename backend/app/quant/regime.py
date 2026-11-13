"""Clasificador de régimen de mercado (D67).

Núcleo puro: solo polars, numpy y esquemas.
"""

import math

import polars as pl

from app.quant.features import rolling_volatility
from app.quant.regime_stats import adf_pvalue, hurst_exponent, zscore
from app.schemas.enums import RegimeLabel
from app.schemas.quant import RegimeReport, RegimeStats, RegimeThresholds

VOL_SHORT_WINDOW = 20
VOL_LONG_WINDOW = 100
ZSCORE_WINDOW = 50


def _volatility_ratio(close: pl.Series) -> float:
    """Volatilidad móvil corta (20) / larga (100) de los log-retornos en la última vela.

    Misma convención que `features.rolling_volatility` (ddof=1). Devuelve `nan` si no
    hay 100 log-retornos (menos de 101 precios) o si la volatilidad larga es 0.
    """
    frame = pl.DataFrame({"close": close.cast(pl.Float64)})
    out = frame.select(
        short=rolling_volatility(VOL_SHORT_WINDOW), long=rolling_volatility(VOL_LONG_WINDOW)
    ).tail(1)
    short, long_ = out["short"][0], out["long"][0]
    if short is None or long_ is None or not long_ > 0.0:
        return float("nan")
    return float(short) / float(long_)


def _last_zscore(close: pl.Series, window: int) -> float:
    z = zscore(close, window).tail(1)[0]
    return float("nan") if z is None else float(z)


def classify_regime(
    close: pl.Series,
    thresholds: RegimeThresholds = RegimeThresholds(),  # noqa: B008 (esquema inmutable)
    zscore_window: int = ZSCORE_WINDOW,
) -> RegimeReport:
    """Clasifica el régimen de una serie de cierres según reglas explícitas (D67).

    Estadísticos: `hurst` y `adf_pvalue` sobre los precios (con `thresholds.min_obs`);
    `zscore` = último z-score móvil (ventana `zscore_window`, 50 por defecto);
    `volatility_ratio` = std móvil de 20 / std móvil de 100 de los log-retornos en la
    última vela (`nan` si no hay datos suficientes o la std larga es 0).

    Reglas, en orden de precedencia (gana la primera que se cumpla):

    1. `len(close) < min_obs` -> `ValueError` en español.
    2. `volatility_ratio >= vol_ratio_high` -> `HIGH_VOLATILITY_NOISE` (gana aunque
       Hurst/ADF indiquen reversión). Un ratio `nan` no cuenta como alta volatilidad.
    3. `hurst < hurst_mean_reverting` y `adf_pvalue < adf_alpha` -> `MEAN_REVERTING`.
    4. `hurst > hurst_trending` -> `TRENDING`.
    5. Cualquier otro caso (inconcluyente, incluidos `hurst`/`adf_pvalue` `nan` por
       serie constante) -> `HIGH_VOLATILITY_NOISE`: inconcluyente = ruido, la opción
       prudente. Las comparaciones con `nan` son falsas, así que no lanzan excepción.

    Los umbrales usados viajan en el resultado.
    """
    n = len(close)
    if n < thresholds.min_obs:
        raise ValueError(
            f"Datos insuficientes para clasificar el régimen: {n} observaciones, "
            f"se necesitan al menos {thresholds.min_obs}."
        )
    hurst = hurst_exponent(close.to_numpy(), thresholds.min_obs)
    adf_p = adf_pvalue(close.to_numpy(), thresholds.min_obs)
    vol_ratio = _volatility_ratio(close)
    stats = RegimeStats(
        hurst=hurst,
        adf_pvalue=adf_p,
        zscore=_last_zscore(close, zscore_window),
        volatility_ratio=vol_ratio,
        n_obs=n,
    )
    if not math.isnan(vol_ratio) and vol_ratio >= thresholds.vol_ratio_high:
        label = RegimeLabel.HIGH_VOLATILITY_NOISE
    elif hurst < thresholds.hurst_mean_reverting and adf_p < thresholds.adf_alpha:
        label = RegimeLabel.MEAN_REVERTING
    elif hurst > thresholds.hurst_trending:
        label = RegimeLabel.TRENDING
    else:
        label = RegimeLabel.HIGH_VOLATILITY_NOISE
    return RegimeReport(label=label, stats=stats, thresholds=thresholds)
