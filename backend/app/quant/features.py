"""Features básicos como expresiones de polars (causales: el valor en `t` usa solo datos <= t)."""

import polars as pl


def log_returns() -> pl.Expr:
    """Rendimiento logarítmico `ln(close_t / close_{t-1})`; la primera fila es null."""
    return pl.col("close").log().diff()


def rolling_volatility(window: int) -> pl.Expr:
    """Desviación típica muestral (ddof=1) móvil de los rendimientos logarítmicos.

    Las primeras `window` filas son null (el primer rendimiento ya es null y la
    ventana necesita `window` rendimientos válidos).
    """
    if window < 2:
        raise ValueError("window debe ser mayor o igual que 2")
    return log_returns().rolling_std(window_size=window, min_samples=window, ddof=1)


def atr(period: int) -> pl.Expr:
    """Average True Range de Wilder.

    Convención:
    - `TR_t = max(high-low, |high-close_{t-1}|, |low-close_{t-1}|)`; en la primera
      fila (sin cierre previo) `TR = high - low`.
    - Las primeras `period - 1` filas son null.
    - Semilla: `ATR_{period-1}` = media simple de los primeros `period` TR.
    - Después, RMA de Wilder: `ATR_t = (ATR_{t-1} * (period - 1) + TR_t) / period`.
    """
    if period < 1:
        raise ValueError("period debe ser mayor o igual que 1")
    prev_close = pl.col("close").shift(1)
    tr = pl.max_horizontal(
        pl.col("high") - pl.col("low"),
        (pl.col("high") - prev_close).abs(),
        (pl.col("low") - prev_close).abs(),
    )
    idx = pl.int_range(pl.len())
    seeded = (
        pl.when(idx < period - 1)
        .then(None)
        .when(idx == period - 1)
        .then(tr.rolling_mean(window_size=period))
        .otherwise(tr)
    )
    return seeded.ewm_mean(alpha=1.0 / period, adjust=False)
