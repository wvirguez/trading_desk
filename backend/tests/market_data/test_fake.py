from datetime import timedelta

from app.market_data.fake import FakeAdapter
from app.schemas.enums import Provider, Timeframe
from app.schemas.instrument import InstrumentSchema
from tests.market_data.conftest import utc

NOW = utc(2024, 1, 10, 12, 20)


async def test_es_determinista(btc: InstrumentSchema) -> None:
    a = FakeAdapter(seed=7, now=lambda: NOW)
    b = FakeAdapter(seed=7, now=lambda: NOW)
    start, end = utc(2024, 1, 1), utc(2024, 1, 3)
    assert await a.fetch_ohlcv(btc, Timeframe.H1, start, end) == await b.fetch_ohlcv(
        btc, Timeframe.H1, start, end
    )


async def test_semillas_distintas_dan_velas_distintas(btc: InstrumentSchema) -> None:
    start, end = utc(2024, 1, 1), utc(2024, 1, 3)
    a = await FakeAdapter(seed=1, now=lambda: NOW).fetch_ohlcv(btc, Timeframe.H1, start, end)
    b = await FakeAdapter(seed=2, now=lambda: NOW).fetch_ohlcv(btc, Timeframe.H1, start, end)
    assert a != b


async def test_rangos_solapados_dan_la_misma_vela(btc: InstrumentSchema) -> None:
    adapter = FakeAdapter(seed=3, now=lambda: NOW)
    full = await adapter.fetch_ohlcv(btc, Timeframe.H1, utc(2024, 1, 1), utc(2024, 1, 2))
    part = await adapter.fetch_ohlcv(btc, Timeframe.H1, utc(2024, 1, 1, 10), utc(2024, 1, 1, 14))
    assert part == full[10:14]


async def test_respeta_start_end_y_alineacion(btc: InstrumentSchema) -> None:
    adapter = FakeAdapter(seed=1, now=lambda: NOW)
    # start desalineado: la primera vela es la siguiente alineada (>= start).
    candles = await adapter.fetch_ohlcv(
        btc, Timeframe.H1, utc(2024, 1, 1, 0, 30), utc(2024, 1, 1, 5)
    )
    assert [c.ts.hour for c in candles] == [1, 2, 3, 4]
    assert all(c.timeframe is Timeframe.H1 and c.symbol == "BTC/USDT" for c in candles)
    assert adapter.provider is Provider.BINANCE


async def test_no_devuelve_velas_abiertas(btc: InstrumentSchema) -> None:
    adapter = FakeAdapter(seed=1, now=lambda: NOW)
    candles = await adapter.fetch_ohlcv(btc, Timeframe.H1, utc(2024, 1, 10), utc(2024, 1, 11))
    assert candles[-1].ts == utc(2024, 1, 10, 11)
    assert candles[-1].ts + timedelta(hours=1) <= NOW


async def test_genera_velas_validas_en_todos_los_timeframes(btc: InstrumentSchema) -> None:
    adapter = FakeAdapter(seed=5, now=lambda: NOW)
    for tf in Timeframe:
        candles = await adapter.fetch_ohlcv(btc, tf, utc(2024, 1, 1), utc(2024, 1, 5))
        assert candles
        assert candles == sorted(candles, key=lambda c: c.ts)
        assert len({c.ts for c in candles}) == len(candles)
