from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.market_data.base import MarketDataError
from app.market_data.ccxt_adapter import CcxtAdapter
from app.schemas.enums import Provider, Timeframe
from app.schemas.instrument import InstrumentSchema
from tests.market_data.conftest import load_fixture, utc

H_MS = 3_600_000
START = utc(2024, 1, 1)
END = utc(2024, 1, 1, 6)
NOW = utc(2024, 1, 1, 5, 30)  # la vela de las 05:00 sigue abierta


class FakeExchange:
    """Devuelve las páginas del fixture en orden y registra las peticiones."""

    def __init__(self, pages: list[list[list[float]]], fail: bool = False) -> None:
        self.pages = list(pages)
        self.calls: list[dict[str, Any]] = []
        self.closed = False
        self.fail = fail

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: int | None = None,
        limit: int | None = None,
    ) -> list[list[float]]:
        self.calls.append(
            {"symbol": symbol, "timeframe": timeframe, "since": since, "limit": limit}
        )
        if self.fail:
            raise RuntimeError("boom")
        return self.pages.pop(0) if self.pages else []

    async def close(self) -> None:
        self.closed = True


def _pages() -> list[list[list[float]]]:
    return [
        load_fixture("binance_btcusdt_1h_page1.json"),
        load_fixture("binance_btcusdt_1h_page2.json"),
    ]


async def test_pagina_deduplica_y_descarta_vela_abierta(btc: InstrumentSchema) -> None:
    exchange = FakeExchange(_pages())
    adapter = CcxtAdapter(exchange, now=lambda: NOW)
    candles = await adapter.fetch_ohlcv(btc, Timeframe.H1, START, END)

    assert adapter.provider is Provider.BINANCE
    assert [c.ts.hour for c in candles] == [0, 1, 2, 3, 4]  # sin duplicado ni vela de las 05:00
    assert all(c.ts.tzinfo is not None and c.ts.utcoffset() == timedelta(0) for c in candles)
    assert all(c.symbol == "BTC/USDT" and c.timeframe is Timeframe.H1 for c in candles)

    first_since = int(START.timestamp() * 1000)
    assert [c["since"] for c in exchange.calls[:2]] == [first_since, first_since + 3 * H_MS]
    assert all(c["limit"] == 1000 and c["timeframe"] == "1h" for c in exchange.calls)
    assert all(c["symbol"] == "BTC/USDT" for c in exchange.calls)


async def test_convierte_a_decimal_exacto(btc: InstrumentSchema) -> None:
    candles = await CcxtAdapter(FakeExchange(_pages()), now=lambda: NOW).fetch_ohlcv(
        btc, Timeframe.H1, START, END
    )
    assert candles[1].volume == Decimal("0.1")
    assert str(candles[1].volume) == "0.1"  # no 0.1000000000000000055...
    assert candles[0].open == Decimal("42000.1")
    assert candles[0].close == Decimal("42050.3")


async def test_cierra_el_exchange_al_terminar(btc: InstrumentSchema) -> None:
    exchange = FakeExchange(_pages())
    await CcxtAdapter(exchange, now=lambda: NOW).fetch_ohlcv(btc, Timeframe.H1, START, END)
    assert exchange.closed


async def test_cierra_el_exchange_y_traduce_el_error(btc: InstrumentSchema) -> None:
    exchange = FakeExchange([], fail=True)
    with pytest.raises(MarketDataError, match="Binance"):
        await CcxtAdapter(exchange, now=lambda: NOW).fetch_ohlcv(btc, Timeframe.H1, START, END)
    assert exchange.closed


async def test_respeta_end(btc: InstrumentSchema) -> None:
    exchange = FakeExchange(_pages())
    candles = await CcxtAdapter(exchange, now=lambda: NOW).fetch_ohlcv(
        btc, Timeframe.H1, START, utc(2024, 1, 1, 3)
    )
    assert [c.ts.hour for c in candles] == [0, 1, 2]


async def test_rechaza_instrumento_de_otro_proveedor(eurusd: InstrumentSchema) -> None:
    with pytest.raises(MarketDataError, match="BINANCE"):
        await CcxtAdapter(FakeExchange([]), now=lambda: NOW).fetch_ohlcv(
            eurusd, Timeframe.H1, START, END
        )


@pytest.mark.parametrize(
    ("tf", "expected", "step_ms"),
    [(Timeframe.M5, "5m", 300_000), (Timeframe.M15, "15m", 900_000), (Timeframe.H1, "1h", H_MS)],
)
async def test_envia_el_timeframe_de_ccxt(
    btc: InstrumentSchema, tf: Timeframe, expected: str, step_ms: int
) -> None:
    base = int(START.timestamp() * 1000)
    rows = [[base + i * step_ms, 100.0, 101.0, 99.0, 100.5, 10.0] for i in range(3)]
    exchange = FakeExchange([rows])
    candles = await CcxtAdapter(exchange, now=lambda: END).fetch_ohlcv(btc, tf, START, END)
    assert exchange.calls[0]["timeframe"] == expected
    assert [c.timeframe for c in candles] == [tf] * 3
    assert candles[1].ts - candles[0].ts == tf.duration
