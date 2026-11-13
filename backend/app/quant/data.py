"""Conversión de velas a `polars.DataFrame`.

Único punto `Decimal -> float` del motor cuantitativo (D52).
"""

from collections.abc import Sequence
from itertools import pairwise

import polars as pl

from app.schemas.candle import CandleSchema

COLUMNS: tuple[str, ...] = ("ts", "open", "high", "low", "close", "volume")


def candles_to_frame(candles: Sequence[CandleSchema]) -> pl.DataFrame:
    """Convierte velas a un DataFrame con `ts` (datetime UTC) y OHLCV en Float64.

    Lanza `ValueError` si los `ts` están duplicados o no son estrictamente ascendentes.
    """
    for prev, cur in pairwise(candles):
        if cur.ts == prev.ts:
            raise ValueError(f"Hay velas con ts duplicado: {cur.ts.isoformat()}")
        if cur.ts < prev.ts:
            raise ValueError(
                f"Las velas deben estar en orden ascendente: {cur.ts.isoformat()} "
                f"aparece después de {prev.ts.isoformat()}"
            )
    return pl.DataFrame(
        {
            "ts": [c.ts for c in candles],
            "open": [float(c.open) for c in candles],
            "high": [float(c.high) for c in candles],
            "low": [float(c.low) for c in candles],
            "close": [float(c.close) for c in candles],
            "volume": [float(c.volume) for c in candles],
        },
        schema={
            "ts": pl.Datetime("us", "UTC"),
            "open": pl.Float64,
            "high": pl.Float64,
            "low": pl.Float64,
            "close": pl.Float64,
            "volume": pl.Float64,
        },
    )
