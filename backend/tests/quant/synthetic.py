"""Series sintéticas con semilla fija para los tests del motor cuantitativo.

Todas devuelven `numpy.ndarray` float64 de longitud `n` y son deterministas para
una misma `seed` (`numpy.random.default_rng(seed)`). Son series de NIVELES (precios).
"""

import numpy as np
from numpy.typing import NDArray

Series = NDArray[np.float64]


def random_walk(n: int, seed: int = 42, start: float = 100.0, sigma: float = 1.0) -> Series:
    """Paseo aleatorio `x_t = x_{t-1} + eps_t`, `eps ~ N(0, sigma^2)`."""
    rng = np.random.default_rng(seed)
    steps = rng.normal(0.0, sigma, n)
    steps[0] = 0.0
    return np.asarray(start + np.cumsum(steps), dtype=np.float64)


def mean_reverting(
    n: int, seed: int = 42, mean: float = 100.0, phi: float = 0.9, sigma: float = 1.0
) -> Series:
    """Ornstein-Uhlenbeck discreto `x_t - mean = phi (x_{t-1} - mean) + eps_t`."""
    rng = np.random.default_rng(seed)
    eps = rng.normal(0.0, sigma, n)
    x = np.empty(n, dtype=np.float64)
    x[0] = mean
    for t in range(1, n):
        x[t] = mean + phi * (x[t - 1] - mean) + eps[t]
    return x


def trending(
    n: int,
    seed: int = 42,
    start: float = 100.0,
    drift: float = 0.2,
    phi: float = 0.7,
    sigma: float = 1.0,
) -> Series:
    """Serie con tendencia: incrementos `d_t = drift + u_t`, `u_t = phi u_{t-1} + eps_t`.

    La deriva sola no es detectable por el estimador de Hurst (D53), que mide la
    dispersión de los incrementos y no su media; la persistencia (`phi > 0`) de los
    incrementos es lo que produce `H > 0.5`.
    """
    rng = np.random.default_rng(seed)
    eps = rng.normal(0.0, sigma, n)
    u = np.zeros(n, dtype=np.float64)
    for t in range(1, n):
        u[t] = phi * u[t - 1] + eps[t]
    steps = drift + u
    steps[0] = 0.0
    return np.asarray(start + np.cumsum(steps), dtype=np.float64)
