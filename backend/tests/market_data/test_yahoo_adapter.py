"""Pruebas del adaptador de Yahoo Finance: sin red, con descargador falso (D35)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd
import pytest

from app.market_data.base import MarketDataError, UnsupportedTimeframeError
from app.market_data.yahoo import HistoryNotice, PartialBlocksNotice, YahooAdapter
from app.schemas.enums import AssetClass, Provider, SessionType, Timeframe
from app.schemas.instrument import InstrumentSchema
from tests.market_data.conftest import load_fixture, make_instrument, utc

Call = tuple[str, str, datetime, datetime]


def frame_from_fixture(name: str) -> pd.DataFrame:
    """Reproduce la forma que devuelve yfinance: índice con zona horaria y columnas OHLCV."""
    data = load_fixture(name)
    index = pd.DatetimeIndex(pd.to_datetime([r["ts"] for r in data["rows"]], utc=True)).tz_convert(
        data["tz"]
    )
    return pd.DataFrame(
        {
            "Open": [r["open"] for r in data["rows"]],
            "High": [r["high"] for r in data["rows"]],
            "Low": [r["low"] for r in data["rows"]],
            "Close": [r["close"] for r in data["rows"]],
            "Volume": [r["volume"] for r in data["rows"]],
        },
        index=index,
    )


class FakeDownloader:
    def __init__(self, frame: pd.DataFrame | None = None, error: Exception | None = None) -> None:
        self.frame = frame
        self.error = error
        self.calls: list[Call] = []

    def __call__(self, ticker: str, interval: str, start: datetime, end: datetime) -> pd.DataFrame:
        self.calls.append((ticker, interval, start, end))
        if self.error is not None:
            raise self.error
        assert self.frame is not None
        return self.frame


def _instrument(symbol: str, ticker: str, ac: AssetClass, sess: SessionType) -> InstrumentSchema:
    return make_instrument(symbol, Provider.YAHOO, ticker, ac, "0.00001", "1", sess)


@pytest.fixture
def y_eurusd() -> InstrumentSchema:
    return _instrument("EUR/USD", "EURUSD=X", AssetClass.FX, SessionType.FX_24_5)


@pytest.fixture
def y_xauusd() -> InstrumentSchema:
    return _instrument("XAU/USD", "GC=F", AssetClass.METAL, SessionType.FX_24_5)


@pytest.fixture
def y_nas100() -> InstrumentSchema:
    return _instrument("NAS100", "^NDX", AssetClass.INDEX, SessionType.INDEX_CFD)


def _adapter(downloader: FakeDownloader, now: datetime | None = None) -> YahooAdapter:
    clock = now or utc(2024, 1, 10)
    return YahooAdapter(downloader, now=lambda: clock)


async def test_mapeo_ticker_e_intervalo(y_eurusd: InstrumentSchema) -> None:
    cases = {
        Timeframe.M5: "yahoo_eurusd_5m.json",
        Timeframe.M15: "yahoo_nas100_15m.json",
        Timeframe.H1: "yahoo_eurusd_1h.json",
    }
    expected = {Timeframe.M5: "5m", Timeframe.M15: "15m", Timeframe.H1: "1h"}
    for tf, fixture in cases.items():
        dl = FakeDownloader(frame_from_fixture(fixture))
        adapter = _adapter(dl)
        await adapter.fetch_ohlcv(y_eurusd, tf, utc(2024, 1, 5), utc(2024, 1, 9))
        assert adapter.provider is Provider.YAHOO
        assert dl.calls[0][0] == "EURUSD=X"
        assert dl.calls[0][1] == expected[tf]


async def test_5m_decimal_exacto_utc_y_volumen_cero(y_eurusd: InstrumentSchema) -> None:
    dl = FakeDownloader(frame_from_fixture("yahoo_eurusd_5m.json"))
    candles = await _adapter(dl).fetch_ohlcv(
        y_eurusd, Timeframe.M5, utc(2024, 1, 8, 9), utc(2024, 1, 8, 10)
    )
    assert len(candles) == 6
    first = candles[0]
    assert first.ts == utc(2024, 1, 8, 9) and first.ts.utcoffset() == timedelta(0)
    assert first.timeframe is Timeframe.M5 and first.symbol == "EUR/USD"
    assert first.open == Decimal("1.095")
    assert first.high == Decimal("1.0955")
    assert first.low == Decimal("1.0947")
    assert first.close == Decimal("1.0952")
    assert first.volume == Decimal("0")
    assert all(isinstance(c.open, Decimal) for c in candles)
    assert candles[1].open == Decimal("1.09502")


async def test_15m_con_volumen_y_zona_horaria_a_utc(y_nas100: InstrumentSchema) -> None:
    dl = FakeDownloader(frame_from_fixture("yahoo_nas100_15m.json"))
    candles = await _adapter(dl).fetch_ohlcv(
        y_nas100, Timeframe.M15, utc(2024, 1, 8, 14), utc(2024, 1, 8, 17)
    )
    assert len(candles) == 6
    assert candles[0].ts == utc(2024, 1, 8, 14, 30)
    assert candles[0].open == Decimal("16800.25")
    assert candles[0].volume == Decimal("1200000")
    assert candles[-1].ts == utc(2024, 1, 8, 15, 45)


async def test_solo_velas_cerradas_orden_y_duplicados(y_eurusd: InstrumentSchema) -> None:
    frame = frame_from_fixture("yahoo_eurusd_5m.json")
    frame = pd.concat([frame.iloc[::-1], frame.iloc[[2]]])  # desordenado + duplicado
    now = utc(2024, 1, 8, 9, 22)  # la vela de 09:20 sigue abierta
    candles = await _adapter(FakeDownloader(frame), now).fetch_ohlcv(
        y_eurusd, Timeframe.M5, utc(2024, 1, 8, 9), utc(2024, 1, 8, 10)
    )
    assert [c.ts for c in candles] == [utc(2024, 1, 8, 9, m) for m in (0, 5, 10, 15)]


async def test_filtra_por_rango(y_eurusd: InstrumentSchema) -> None:
    dl = FakeDownloader(frame_from_fixture("yahoo_eurusd_5m.json"))
    candles = await _adapter(dl).fetch_ohlcv(
        y_eurusd, Timeframe.M5, utc(2024, 1, 8, 9, 10), utc(2024, 1, 8, 9, 20)
    )
    assert [c.ts for c in candles] == [utc(2024, 1, 8, 9, 10), utc(2024, 1, 8, 9, 15)]


async def test_descarta_filas_con_nan_y_volumen_nan_es_cero(y_eurusd: InstrumentSchema) -> None:
    frame = frame_from_fixture("yahoo_eurusd_5m.json")
    frame.iloc[1, frame.columns.get_loc("Close")] = float("nan")
    frame.iloc[2, frame.columns.get_loc("Volume")] = float("nan")
    candles = await _adapter(FakeDownloader(frame)).fetch_ohlcv(
        y_eurusd, Timeframe.M5, utc(2024, 1, 8, 9), utc(2024, 1, 8, 10)
    )
    assert len(candles) == 5
    assert utc(2024, 1, 8, 9, 5) not in [c.ts for c in candles]
    assert candles[1].volume == Decimal("0")


def _hourly_frame(hours: list[tuple[int, int]], volume: float = 10.0) -> pd.DataFrame:
    """Velas de 1h (día, hora UTC) del 2024-01-08 + días siguientes; precios deterministas."""
    index = pd.DatetimeIndex([datetime(2024, 1, d, h, tzinfo=UTC) for d, h in hours])
    n = len(hours)
    return pd.DataFrame(
        {
            "Open": [1.0 + i for i in range(n)],
            "High": [10.0 + i for i in range(n)],
            "Low": [0.5 + i for i in range(n)],
            "Close": [2.0 + i for i in range(n)],
            "Volume": [volume] * n,
        },
        index=index,
    )


async def test_4h_desde_1h_emite_bloques_parciales_y_avisa(y_eurusd: InstrumentSchema) -> None:
    dl = FakeDownloader(frame_from_fixture("yahoo_eurusd_1h.json"))
    adapter = _adapter(dl, utc(2024, 1, 9))
    candles = await adapter.fetch_ohlcv(
        y_eurusd, Timeframe.H4, utc(2024, 1, 5, 12), utc(2024, 1, 8, 16)
    )
    # Se pide 1h a Yahoo, ampliando el rango a bloques de 4h completos.
    assert dl.calls[0][1] == "1h"
    assert dl.calls[0][2] <= utc(2024, 1, 5, 12) and dl.calls[0][3] >= utc(2024, 1, 8, 16)
    assert [c.ts for c in candles] == [
        utc(2024, 1, 5, 12),
        utc(2024, 1, 5, 16),
        utc(2024, 1, 5, 20),  # parcial: solo la vela de 20:00
        utc(2024, 1, 7, 20),  # parcial: reapertura del domingo, 22:00 y 23:00
        utc(2024, 1, 8, 0),
        utc(2024, 1, 8, 4),
        utc(2024, 1, 8, 8),
        utc(2024, 1, 8, 12),
    ]
    assert all(c.timeframe is Timeframe.H4 for c in candles)
    mon = candles[4]
    assert (mon.open, mon.high, mon.low, mon.close) == (
        Decimal("1.0811"),
        Decimal("1.0819"),
        Decimal("1.0808"),
        Decimal("1.0816"),
    )
    assert mon.volume == Decimal("0")
    fri = candles[1]  # 16-20: la fila duplicada de 15:00 no cuenta como vela extra
    assert (fri.open, fri.high, fri.low, fri.close) == (
        Decimal("1.0804"),
        Decimal("1.0812"),
        Decimal("1.0801"),
        Decimal("1.0809"),
    )
    notice = adapter.partial_notice
    assert notice == PartialBlocksNotice(partial=3, total=8)
    assert adapter.notices[-1] is notice


async def test_4h_suma_volumen_y_no_emite_bloque_abierto(y_eurusd: InstrumentSchema) -> None:
    frame = _hourly_frame([(8, h) for h in range(8)])
    frame["Volume"] = [10.0, 20.0, 30.0, 40.0, 1.0, 1.0, 1.0, 1.0]
    # now = 06:00: el bloque 04-08 aún está abierto y no se emite
    adapter = _adapter(FakeDownloader(frame), utc(2024, 1, 8, 6))
    candles = await adapter.fetch_ohlcv(y_eurusd, Timeframe.H4, utc(2024, 1, 8), utc(2024, 1, 8, 8))
    assert len(candles) == 1
    assert candles[0].volume == Decimal("100")
    assert adapter.partial_notice is None  # el bloque emitido tiene las 4 velas


async def test_4h_bloque_parcial_de_gc_f_con_3_velas(y_xauusd: InstrumentSchema) -> None:
    # Futuro GC=F: de 20:00 a 24:00 UTC hay hueco (cierre diario), llegan 3 velas de 1h.
    frame = _hourly_frame([(8, 16), (8, 17), (8, 18), (8, 19), (8, 20), (8, 21), (8, 22)])
    adapter = _adapter(FakeDownloader(frame), utc(2024, 1, 9))
    candles = await adapter.fetch_ohlcv(
        y_xauusd, Timeframe.H4, utc(2024, 1, 8, 16), utc(2024, 1, 9)
    )
    assert [c.ts for c in candles] == [utc(2024, 1, 8, 16), utc(2024, 1, 8, 20)]
    last = candles[1]
    assert last.open == Decimal("5")  # primera vela presente (20:00)
    assert last.high == Decimal("16")  # máx. de las tres
    assert last.low == Decimal("4.5")  # mín.
    assert last.close == Decimal("8")  # última presente (22:00)
    assert last.volume == Decimal("30")
    assert adapter.partial_notice == PartialBlocksNotice(partial=1, total=2)
    msg = adapter.partial_notice.message
    assert "1 de 2 bloques" in msg and "menos de 4 velas de 1h" in msg


async def test_4h_bloque_con_una_sola_vela(y_xauusd: InstrumentSchema) -> None:
    frame = _hourly_frame([(8, 4), (8, 5), (8, 6), (8, 7), (8, 12)])
    adapter = _adapter(FakeDownloader(frame), utc(2024, 1, 9))
    candles = await adapter.fetch_ohlcv(
        y_xauusd, Timeframe.H4, utc(2024, 1, 8, 4), utc(2024, 1, 8, 16)
    )
    assert [c.ts for c in candles] == [utc(2024, 1, 8, 4), utc(2024, 1, 8, 12)]
    single = candles[1]
    assert (single.open, single.high, single.low, single.close) == (
        Decimal("5"),
        Decimal("14"),
        Decimal("4.5"),
        Decimal("6"),
    )
    assert single.volume == Decimal("10")
    assert adapter.partial_notice == PartialBlocksNotice(partial=1, total=2)


async def test_4h_bloque_con_4_velas_no_es_parcial(y_eurusd: InstrumentSchema) -> None:
    frame = _hourly_frame([(8, h) for h in (0, 1, 2, 3)])
    adapter = _adapter(FakeDownloader(frame), utc(2024, 1, 9))
    candles = await adapter.fetch_ohlcv(y_eurusd, Timeframe.H4, utc(2024, 1, 8), utc(2024, 1, 8, 4))
    assert len(candles) == 1
    assert adapter.partial_notice is None and adapter.notices == []


async def test_4h_bloque_aun_abierto_no_se_emite_ni_cuenta(y_eurusd: InstrumentSchema) -> None:
    frame = _hourly_frame([(8, 0), (8, 1), (8, 2), (8, 3), (8, 4), (8, 5)])
    # now = 07:00: el bloque 04-08 (parcial por ahora) todavía no ha terminado
    adapter = _adapter(FakeDownloader(frame), utc(2024, 1, 8, 7))
    candles = await adapter.fetch_ohlcv(y_eurusd, Timeframe.H4, utc(2024, 1, 8), utc(2024, 1, 8, 8))
    assert [c.ts for c in candles] == [utc(2024, 1, 8, 0)]
    assert adapter.partial_notice is None


async def test_avisos_de_historia_y_bloques_parciales_coexisten(
    y_xauusd: InstrumentSchema,
) -> None:
    now = utc(2024, 3, 1)
    frame = _hourly_frame([(8, 4), (8, 5)])
    adapter = _adapter(FakeDownloader(frame), now)
    await adapter.fetch_ohlcv(y_xauusd, Timeframe.H4, now - timedelta(days=1000), now)
    assert [type(n) for n in adapter.notices] == [HistoryNotice, PartialBlocksNotice]


@pytest.mark.parametrize("tf", [Timeframe.H1, Timeframe.H4])
async def test_nas100_1h_y_4h_no_soportados_sin_llamar_al_descargador(
    y_nas100: InstrumentSchema, tf: Timeframe
) -> None:
    # Fixture con velas de 1h a :30 UTC, como las entrega Yahoo para ^NDX (2026-11-13).
    dl = FakeDownloader(frame_from_fixture("yahoo_nas100_1h.json"))
    adapter = _adapter(dl)
    with pytest.raises(UnsupportedTimeframeError, match=r"\^NDX.*:30.*5m, 15m y 1d"):
        await adapter.fetch_ohlcv(y_nas100, tf, utc(2024, 1, 8), utc(2024, 1, 9))
    assert dl.calls == []
    assert isinstance(UnsupportedTimeframeError("x"), MarketDataError)


@pytest.mark.parametrize("tf", [Timeframe.M5, Timeframe.M15])
async def test_nas100_5m_y_15m_si_se_piden(y_nas100: InstrumentSchema, tf: Timeframe) -> None:
    dl = FakeDownloader(frame_from_fixture("yahoo_nas100_15m.json"))
    await _adapter(dl).fetch_ohlcv(y_nas100, tf, utc(2024, 1, 8), utc(2024, 1, 9))
    assert len(dl.calls) == 1


async def test_diaria_alineada_a_medianoche_utc(y_xauusd: InstrumentSchema) -> None:
    dl = FakeDownloader(frame_from_fixture("yahoo_xauusd_1d.json"))
    candles = await _adapter(dl, utc(2024, 3, 20)).fetch_ohlcv(
        y_xauusd, Timeframe.D1, utc(2024, 3, 1), utc(2024, 3, 15)
    )
    assert dl.calls[0][:2] == ("GC=F", "1d")
    # Antes y después del cambio de hora de EE. UU. (10-mar) la fecha local manda
    assert [c.ts for c in candles] == [
        utc(2024, 3, 7),
        utc(2024, 3, 8),
        utc(2024, 3, 11),
        utc(2024, 3, 12),
    ]
    assert candles[0].open == Decimal("2170.5")
    assert candles[0].volume == Decimal("150000")
    assert candles[0].timeframe is Timeframe.D1


async def test_diaria_ambigua_falla(y_xauusd: InstrumentSchema) -> None:
    frame = frame_from_fixture("yahoo_xauusd_1d.json")
    frame.index = frame.index + pd.Timedelta(hours=13, minutes=30)  # 13:30 locales
    with pytest.raises(MarketDataError, match="diaria"):
        await _adapter(FakeDownloader(frame), utc(2024, 3, 20)).fetch_ohlcv(
            y_xauusd, Timeframe.D1, utc(2024, 3, 1), utc(2024, 3, 15)
        )


async def test_diaria_con_fecha_repetida_distinta_falla(y_xauusd: InstrumentSchema) -> None:
    frame = frame_from_fixture("yahoo_xauusd_1d.json")
    # Misma fecha con dos filas de datos distintos: no se puede elegir sin ambigüedad
    extra = frame.iloc[[0]].copy()
    extra["Close"] = 2171.0
    frame = pd.concat([frame, extra])
    with pytest.raises(MarketDataError, match="diaria"):
        await _adapter(FakeDownloader(frame), utc(2024, 3, 20)).fetch_ohlcv(
            y_xauusd, Timeframe.D1, utc(2024, 3, 1), utc(2024, 3, 15)
        )


async def test_error_de_red_es_market_data_error(y_eurusd: InstrumentSchema) -> None:
    dl = FakeDownloader(error=ConnectionError("sin red"))
    with pytest.raises(MarketDataError, match="Yahoo"):
        await _adapter(dl).fetch_ohlcv(y_eurusd, Timeframe.M5, utc(2024, 1, 8), utc(2024, 1, 9))


async def test_respuesta_vacia_devuelve_lista_vacia_con_aviso(y_eurusd: InstrumentSchema) -> None:
    empty = pd.DataFrame({c: [] for c in ("Open", "High", "Low", "Close", "Volume")})
    adapter = _adapter(FakeDownloader(empty))
    candles = await adapter.fetch_ohlcv(y_eurusd, Timeframe.M5, utc(2024, 1, 8), utc(2024, 1, 9))
    assert candles == []
    messages = [n.message for n in adapter.notices]
    assert len(messages) == 1
    assert "no devolvió velas" in messages[0]
    assert "EURUSD=X" in messages[0]
    assert "5m" in messages[0]
    # el aviso se reinicia en la llamada siguiente
    await adapter.fetch_ohlcv(y_eurusd, Timeframe.M5, utc(2024, 1, 9), utc(2024, 1, 9))
    assert adapter.empty_notice is None


async def test_columnas_faltantes_es_market_data_error(y_eurusd: InstrumentSchema) -> None:
    frame = frame_from_fixture("yahoo_eurusd_5m.json").drop(columns=["High"])
    with pytest.raises(MarketDataError, match="High"):
        await _adapter(FakeDownloader(frame)).fetch_ohlcv(
            y_eurusd, Timeframe.M5, utc(2024, 1, 8), utc(2024, 1, 9)
        )


async def test_proveedor_incorrecto(btc: InstrumentSchema) -> None:
    with pytest.raises(MarketDataError, match="YAHOO"):
        await _adapter(FakeDownloader()).fetch_ohlcv(
            btc, Timeframe.M5, utc(2024, 1, 8), utc(2024, 1, 9)
        )


async def test_aviso_si_se_pide_mas_historia_que_el_limite(y_eurusd: InstrumentSchema) -> None:
    now = utc(2024, 3, 1)
    dl = FakeDownloader(frame_from_fixture("yahoo_eurusd_5m.json"))
    adapter = _adapter(dl, now)
    assert adapter.history_notice is None
    await adapter.fetch_ohlcv(y_eurusd, Timeframe.M5, now - timedelta(days=90), now)
    # Yahoo rechaza 5m con más de 59 días: el adaptador recorta la petición y lo dice
    assert dl.calls[0][2] == now - timedelta(days=59)
    notice: Any = adapter.history_notice
    assert isinstance(notice, HistoryNotice)
    assert notice.timeframe is Timeframe.M5
    assert notice.requested_start == now - timedelta(days=90)
    assert notice.available_start == now - timedelta(days=59)
    assert "59" in notice.message and "5m" in notice.message


async def test_sin_aviso_dentro_del_limite(y_eurusd: InstrumentSchema) -> None:
    now = utc(2024, 3, 1)
    dl = FakeDownloader(frame_from_fixture("yahoo_eurusd_5m.json"))
    adapter = _adapter(dl, now)
    # El servicio calcula `start` unos instantes antes que `now` del adaptador: tolerancia
    await adapter.fetch_ohlcv(y_eurusd, Timeframe.M5, now - timedelta(days=59, seconds=2), now)
    assert adapter.history_notice is None


async def test_todo_fuera_del_limite_devuelve_vacio_con_aviso(y_eurusd: InstrumentSchema) -> None:
    now = utc(2024, 3, 1)
    dl = FakeDownloader()
    adapter = _adapter(dl, now)
    out = await adapter.fetch_ohlcv(
        y_eurusd, Timeframe.M15, now - timedelta(days=200), now - timedelta(days=100)
    )
    assert out == []
    assert dl.calls == []
    assert adapter.history_notice is not None
