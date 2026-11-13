"""Tests de los estadísticos de régimen con series sintéticas (1000 puntos, semilla fija)."""

import math
from collections.abc import Callable

import numpy as np
import polars as pl
import pytest

from app.quant.regime_stats import adf_pvalue, hurst_exponent, zscore
from tests.quant.synthetic import mean_reverting, random_walk, trending

N = 1000
SEED = 42


def test_hurst_random_walk() -> None:
    assert 0.4 <= hurst_exponent(random_walk(N, SEED)) <= 0.6


def test_hurst_mean_reverting() -> None:
    assert hurst_exponent(mean_reverting(N, SEED)) < 0.4


def test_hurst_trending() -> None:
    assert hurst_exponent(trending(N, SEED)) > 0.6


def test_adf_mean_reverting_stationary() -> None:
    assert adf_pvalue(mean_reverting(N, SEED)) < 0.05


def test_adf_random_walk_unit_root() -> None:
    assert adf_pvalue(random_walk(N, SEED)) > 0.05


def test_synthetic_deterministic() -> None:
    assert np.array_equal(random_walk(50, 1), random_walk(50, 1))
    assert not np.array_equal(random_walk(50, 1), random_walk(50, 2))


def test_zscore_reference_values() -> None:
    # Ventana 3 sobre [1,2,4,8]: [1,2,4] -> media 7/3, std 1.5275252316519465
    # z = (4 - 7/3)/1.5275... = 1.0910894511799619 ; [2,4,8] -> media 14/3,
    # std 3.0550504633038935 ; z = (8 - 14/3)/3.0550... = 1.0910894511799619
    z = zscore(pl.Series([1.0, 2.0, 4.0, 8.0]), 3)
    assert z[0] is None
    assert z[1] is None
    assert z[2] == pytest.approx(1.0910894511799619)
    assert z[3] == pytest.approx(1.0910894511799619)


def test_zscore_simple_hand_value() -> None:
    # [1,2,3]: media 2, std 1 -> z del último = 1.0
    z = zscore(pl.Series([1.0, 2.0, 3.0]), 3)
    assert z[2] == pytest.approx(1.0)


def test_zscore_constant_is_null() -> None:
    z = zscore(pl.Series([5.0] * 10), 4)
    assert z.null_count() == 10


def test_zscore_causal() -> None:
    s = pl.Series(random_walk(60, 3))
    assert zscore(s, 10)[:30].to_list() == zscore(s[:30], 10).to_list()


def test_zscore_invalid_window() -> None:
    with pytest.raises(ValueError):
        zscore(pl.Series([1.0, 2.0]), 1)


@pytest.mark.parametrize("fn", [hurst_exponent, adf_pvalue])
def test_nan_with_few_observations(fn: Callable[..., float]) -> None:
    assert math.isnan(fn(random_walk(99, SEED)))
    assert not math.isnan(fn(random_walk(100, SEED)))


@pytest.mark.parametrize("fn", [hurst_exponent, adf_pvalue])
def test_nan_constant_series(fn: Callable[..., float]) -> None:
    assert math.isnan(fn(np.full(500, 3.0)))


def test_min_obs_parameter() -> None:
    assert not math.isnan(hurst_exponent(random_walk(60, SEED), min_obs=50))
