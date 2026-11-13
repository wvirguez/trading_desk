from datetime import UTC, datetime, timedelta
from decimal import Decimal

import polars as pl
import pytest

from app.quant.data import candles_to_frame
from app.quant.features import atr, log_returns, rolling_volatility
from app.schemas.candle import CandleSchema
from app.schemas.enums import Timeframe

T0 = datetime(2026, 1, 1, tzinfo=UTC)

# (open, high, low, close) de 10 velas diarias.
OHLC = [
    (100, 102, 98, 100),
    (100, 103, 99, 102),
    (102, 104, 99, 101),
    (101, 106, 100, 105),
    (105, 106, 102, 103),
    (103, 105, 102, 104),
    (104, 109, 104, 108),
    (108, 109, 105, 106),
    (106, 108, 105, 107),
    (107, 111, 107, 110),
]


def _candle(i: int, o: int, h: int, low: int, c: int) -> CandleSchema:
    return CandleSchema(
        symbol="TEST",
        timeframe=Timeframe.D1,
        ts=T0 + timedelta(days=i),
        open=Decimal(o),
        high=Decimal(h),
        low=Decimal(low),
        close=Decimal(c),
        volume=Decimal(1000),
    )


@pytest.fixture
def df() -> pl.DataFrame:
    return candles_to_frame([_candle(i, *row) for i, row in enumerate(OHLC)])


# log_returns: r_t = ln(close_t / close_{t-1}), closes = 100,102,101,105,103,104,108,106,107,110
# r1=ln(102/100)=0.019802627, r2=ln(101/102)=-0.009852296, r3=ln(105/101)=0.038839833,
# r4=ln(103/105)=-0.019231362, r5=ln(104/103)=0.009661911, r6=ln(108/104)=0.037740328,
# r7=ln(106/108)=-0.018692133, r8=ln(107/106)=0.009389740, r9=ln(110/107)=0.027651531
RETURNS = [
    0.01980262729617973,
    -0.009852296443011594,
    0.03883983331626396,
    -0.019231361927887644,
    0.00966191091173689,
    0.03774032798284711,
    -0.01869213301215252,
    0.009389740349839137,
    0.02765153133050995,
]

# rolling_volatility(3): desviación muestral (ddof=1) de 3 rendimientos consecutivos,
# sqrt(sum((x-media)^2)/2). Ej. t=3 (r1,r2,r3): media=0.016263388,
# desviaciones=(0.003539, -0.026116, 0.022576) -> suma cuad.=0.001203 -> /2 -> sqrt=0.024538.
# Primer valor válido en t=3 (r0 es null); filas 0..2 son null.
VOL3 = [
    0.02453824639049047,
    0.03117465339809489,
    0.029035713894885736,
    0.028486816166691086,
    0.028216342681766357,
    0.02821633712528954,
    0.023344591972039305,
]

# atr(3): TR_t = max(h-l, |h-c_prev|, |l-c_prev|); TR_0 = h-l.
# TR = [4, 4, 5, 6, 4, 3, 5, 4, 3, 4] (p. ej. t=2: max(5, |104-102|=2, |99-102|=3) = 5;
# t=3: max(6, |106-101|=5, |100-101|=1) = 6).
# Semilla t=2: (4+4+5)/3 = 13/3 = 4.3333. Luego ATR_t = (2*ATR_{t-1} + TR_t)/3:
# t=3: (26/3+6)/3 = 44/9 = 4.8889; t=4: (88/9+4)/3 = 124/27 = 4.5926; ...
ATR3 = [
    13 / 3,
    44 / 9,
    124 / 27,
    4.061728395061729,
    4.374485596707819,
    4.249657064471879,
    3.8331047096479196,
    3.888736473098613,
]


def test_log_returns(df: pl.DataFrame) -> None:
    out = df.select(log_returns().alias("r"))["r"].to_list()
    assert out[0] is None
    assert out[1:] == pytest.approx(RETURNS)


def test_rolling_volatility(df: pl.DataFrame) -> None:
    out = df.select(rolling_volatility(3).alias("v"))["v"].to_list()
    assert out[:3] == [None, None, None]
    assert out[3:] == pytest.approx(VOL3)


def test_atr_wilder(df: pl.DataFrame) -> None:
    out = df.select(atr(3).alias("a"))["a"].to_list()
    assert out[:2] == [None, None]
    assert out[2:] == pytest.approx(ATR3)


def test_atr_period_1_es_el_true_range(df: pl.DataFrame) -> None:
    out = df.select(atr(1).alias("a"))["a"].to_list()
    assert out == pytest.approx([4, 4, 5, 6, 4, 3, 5, 4, 3, 4])


def test_atr_no_negativo(df: pl.DataFrame) -> None:
    out = df.select(atr(3).alias("a"))["a"].drop_nulls()
    assert (out >= 0).all()


@pytest.mark.parametrize("k", [3, 5, 8, 10])
def test_sin_lookahead_por_truncado(df: pl.DataFrame, k: int) -> None:
    exprs = [log_returns().alias("r"), rolling_volatility(3).alias("v"), atr(3).alias("a")]
    full = df.select(exprs).head(k)
    truncated = df.head(k).select(exprs)
    assert full.equals(truncated)


def test_validaciones() -> None:
    with pytest.raises(ValueError, match="window"):
        rolling_volatility(1)
    with pytest.raises(ValueError, match="period"):
        atr(0)


# --- data.py ---


def test_candles_to_frame_esquema(df: pl.DataFrame) -> None:
    assert df.columns == ["ts", "open", "high", "low", "close", "volume"]
    assert df.schema["ts"] == pl.Datetime("us", "UTC")
    for col in ("open", "high", "low", "close", "volume"):
        assert df.schema[col] == pl.Float64
    assert df.height == 10
    assert df["close"][1] == 102.0
    assert df["ts"][0] == T0


def test_candles_to_frame_vacio() -> None:
    assert candles_to_frame([]).height == 0


def test_candles_to_frame_duplicados() -> None:
    c = _candle(0, *OHLC[0])
    with pytest.raises(ValueError, match="duplicado"):
        candles_to_frame([c, c])


def test_candles_to_frame_desordenadas() -> None:
    with pytest.raises(ValueError, match="orden ascendente"):
        candles_to_frame([_candle(1, *OHLC[1]), _candle(0, *OHLC[0])])
