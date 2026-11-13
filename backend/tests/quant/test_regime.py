"""Tests del clasificador de régimen con series sintéticas (1000 puntos, semilla 42)."""

import math

import numpy as np
import polars as pl
import pytest

from app.quant.regime import classify_regime
from app.schemas.enums import RegimeLabel
from app.schemas.quant import RegimeThresholds
from tests.quant.synthetic import mean_reverting, random_walk, trending

N = 1000
SEED = 42


def _s(x: np.ndarray) -> pl.Series:
    return pl.Series("close", x)


def _with_vol_tail(base: np.ndarray, sigma: float = 3.0, tail: int = 30) -> np.ndarray:
    x = base.copy()
    x[-tail:] += np.random.default_rng(7).normal(0.0, sigma, tail)
    return x


def test_mean_reverting() -> None:
    r = classify_regime(_s(mean_reverting(N, SEED)))
    assert r.label == RegimeLabel.MEAN_REVERTING
    assert r.stats.volatility_ratio < r.thresholds.vol_ratio_high


def test_trending() -> None:
    r = classify_regime(_s(trending(N, SEED)))
    assert r.label == RegimeLabel.TRENDING
    assert r.stats.hurst > r.thresholds.hurst_trending


def test_random_walk_inconclusive_is_noise() -> None:
    r = classify_regime(_s(random_walk(N, SEED)))
    assert r.label == RegimeLabel.HIGH_VOLATILITY_NOISE
    assert r.stats.volatility_ratio < r.thresholds.vol_ratio_high  # no es por volatilidad


@pytest.mark.parametrize("base", [mean_reverting(N, SEED), trending(N, SEED)])
def test_high_volatility_takes_precedence(base: np.ndarray) -> None:
    x = _with_vol_tail(base)
    r = classify_regime(_s(x))
    assert r.stats.volatility_ratio >= r.thresholds.vol_ratio_high
    assert r.label == RegimeLabel.HIGH_VOLATILITY_NOISE


def test_precedence_over_mean_reversion_indicators() -> None:
    x = _with_vol_tail(mean_reverting(N, SEED))
    r = classify_regime(_s(x))
    assert r.stats.hurst < r.thresholds.hurst_mean_reverting
    assert r.stats.adf_pvalue < r.thresholds.adf_alpha
    assert r.label == RegimeLabel.HIGH_VOLATILITY_NOISE
    # Sin el filtro de volatilidad, los mismos datos serían reversión a la media.
    relaxed = classify_regime(_s(x), RegimeThresholds(vol_ratio_high=1e9))
    assert relaxed.label == RegimeLabel.MEAN_REVERTING


def test_insufficient_data_raises() -> None:
    with pytest.raises(ValueError, match=r"99 observaciones.*al menos 100"):
        classify_regime(_s(random_walk(99, SEED)))
    with pytest.raises(ValueError, match=r"150 observaciones.*al menos 200"):
        classify_regime(_s(random_walk(150, SEED)), RegimeThresholds(min_obs=200))


def test_thresholds_returned_default_and_custom() -> None:
    x = _s(mean_reverting(N, SEED))
    assert classify_regime(x).thresholds == RegimeThresholds()
    custom = RegimeThresholds(hurst_mean_reverting=0.01, adf_alpha=0.01, min_obs=50)
    r = classify_regime(x, custom)
    assert r.thresholds == custom
    # Con Hurst exigido < 0.01 la reversión ya no se detecta -> inconcluyente.
    assert r.label == RegimeLabel.HIGH_VOLATILITY_NOISE


def test_stats_populated() -> None:
    x = mean_reverting(N, SEED)
    r = classify_regime(_s(x))
    s = r.stats
    assert s.n_obs == N
    assert all(math.isfinite(v) for v in (s.hurst, s.adf_pvalue, s.zscore, s.volatility_ratio))
    window = x[-50:]
    expected = (x[-1] - window.mean()) / window.std(ddof=1)
    assert s.zscore == pytest.approx(expected)


def test_constant_series_is_inconclusive_without_exception() -> None:
    r = classify_regime(_s(np.full(300, 100.0)))
    assert r.label == RegimeLabel.HIGH_VOLATILITY_NOISE
    assert math.isnan(r.stats.hurst) and math.isnan(r.stats.adf_pvalue)
    assert math.isnan(r.stats.volatility_ratio)


def test_volatility_ratio_nan_when_short_history() -> None:
    # 100 precios -> 99 log-retornos: no hay ventana larga; ratio nan, no cuenta como alta vol.
    r = classify_regime(_s(mean_reverting(100, SEED)))
    assert math.isnan(r.stats.volatility_ratio)
    assert r.stats.n_obs == 100
