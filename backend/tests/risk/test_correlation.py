"""Matriz de correlación de log-retornos (D63)."""

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl

from app.risk.correlation import correlation_matrix, pair_correlation

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _frame(returns: np.ndarray, start: int = 0) -> pl.DataFrame:
    """Cierres con los log-retornos dados; len(ts) = len(returns) + 1."""
    closes = 100.0 * np.exp(np.concatenate([[0.0], np.cumsum(returns)]))
    ts = [T0 + timedelta(hours=start + i) for i in range(len(closes))]
    return pl.DataFrame({"ts": ts, "close": closes}).with_columns(
        pl.col("ts").cast(pl.Datetime("us", "UTC"))
    )


def _rets(n: int, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).normal(0, 0.01, n)


def test_identical_series_correlation_one() -> None:
    r = _rets(60, 1)
    m = correlation_matrix({"A": _frame(r), "B": _frame(r)}, 50)
    assert math.isclose(m[("A", "B")], 1.0, abs_tol=1e-9)


def test_opposite_series_correlation_minus_one() -> None:
    r = _rets(60, 2)
    m = correlation_matrix({"A": _frame(r), "B": _frame(-r)}, 50)
    assert math.isclose(m[("A", "B")], -1.0, abs_tol=1e-9)


def test_independent_series_low_correlation() -> None:
    m = correlation_matrix({"A": _frame(_rets(500, 3)), "B": _frame(_rets(500, 4))}, 500)
    assert abs(m[("A", "B")]) < 0.2


def test_keys_sorted_and_pair_lookup_any_order() -> None:
    r = _rets(40, 5)
    m = correlation_matrix({"Z": _frame(r), "A": _frame(r)}, 30)
    assert list(m) == [("A", "Z")]
    assert pair_correlation(m, "Z", "A") == pair_correlation(m, "A", "Z")
    assert math.isnan(pair_correlation(m, "A", "X"))


def test_uses_only_last_window_common_returns() -> None:
    a, b = _rets(80, 6), _rets(80, 7)
    base = correlation_matrix({"A": _frame(a), "B": _frame(b)}, 30)[("A", "B")]
    a2, b2 = a.copy(), b.copy()
    a2[:40] = _rets(40, 8)  # cambia solo datos más viejos que la ventana
    b2[:40] = _rets(40, 9)
    changed = correlation_matrix({"A": _frame(a2), "B": _frame(b2)}, 30)[("A", "B")]
    assert math.isclose(base, changed, abs_tol=1e-12)


def test_inner_join_by_ts() -> None:
    r = _rets(60, 10)
    full = _frame(r)
    shifted = _frame(r[10:], start=10)  # solape parcial, mismos ts y mismos retornos
    m = correlation_matrix({"A": full, "B": shifted}, 100)
    assert math.isclose(m[("A", "B")], 1.0, abs_tol=1e-9)


def test_fewer_than_20_common_is_nan() -> None:
    r = _rets(19, 11)
    m = correlation_matrix({"A": _frame(r), "B": _frame(r)}, 100)
    assert math.isnan(m[("A", "B")])


def test_constant_series_is_nan() -> None:
    m = correlation_matrix({"A": _frame(_rets(60, 12)), "B": _frame(np.zeros(60))}, 50)
    assert math.isnan(m[("A", "B")])
