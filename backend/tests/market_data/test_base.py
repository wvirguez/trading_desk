from datetime import timedelta
from decimal import Decimal

from app.market_data.base import drop_open_candle
from app.schemas.candle import CandleSchema
from app.schemas.enums import Timeframe
from tests.market_data.conftest import utc


def _candle(ts_hour: int) -> CandleSchema:
    return CandleSchema(
        symbol="BTC/USDT",
        timeframe=Timeframe.H1,
        ts=utc(2024, 1, 1, ts_hour),
        open=Decimal(10),
        high=Decimal(11),
        low=Decimal(9),
        close=Decimal(10),
        volume=Decimal(1),
    )


def test_drop_open_candle_conserva_solo_cerradas() -> None:
    candles = [_candle(0), _candle(1), _candle(2)]
    now = utc(2024, 1, 1, 2, 30)
    assert drop_open_candle(candles, Timeframe.H1, now) == candles[:2]


def test_vela_que_cierra_exactamente_ahora_es_cerrada() -> None:
    candles = [_candle(0), _candle(1)]
    now = candles[1].ts + timedelta(hours=1)
    assert drop_open_candle(candles, Timeframe.H1, now) == candles
