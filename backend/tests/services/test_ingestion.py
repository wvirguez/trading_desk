"""Tests `db` del servicio de ingesta y de la CLI, con `FakeAdapter` (sin red)."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.cli.ingest import run
from app.core.config import get_settings
from app.core.db import build_engine
from app.market_data.base import MarketDataAdapter, MarketDataError
from app.market_data.fake import FakeAdapter
from app.market_data.yahoo import YahooAdapter
from app.models.ohlcv_bar import OhlcvBar
from app.repositories import instruments as instruments_repo
from app.schemas.candle import CandleSchema
from app.schemas.enums import Provider, Timeframe
from app.schemas.instrument import InstrumentSchema
from app.services import ingestion
from tests.market_data.test_yahoo_adapter import frame_from_fixture

pytestmark = pytest.mark.db

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
SINCE = NOW - timedelta(hours=48)


def _clock() -> datetime:
    return NOW


def _fake(_: InstrumentSchema) -> FakeAdapter:
    return FakeAdapter(seed=1, now=_clock)


async def _count(session: AsyncSession) -> int:
    return (await session.execute(select(func.count()).select_from(OhlcvBar))).scalar_one()


@pytest.fixture
async def sessionmaker(db_session: AsyncSession) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Fábrica de sesiones para la CLI (`db_session` deja las tablas vacías)."""
    engine = build_engine(get_settings().test_database_url)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def test_backfill_escribe_n_velas_y_repetir_escribe_cero(db_session: AsyncSession) -> None:
    btc = await instruments_repo.get_by_symbol(db_session, "BTC/USDT")
    assert btc is not None
    adapter = FakeAdapter(seed=1, now=_clock)
    first = await ingestion.backfill(db_session, adapter, btc, Timeframe.H1, SINCE, now=NOW)
    assert (first.fetched, first.written) == (48, 48)
    assert first.symbol == "BTC/USDT"
    assert first.timeframe is Timeframe.H1
    assert first.first_ts == SINCE
    assert first.last_ts == NOW - timedelta(hours=1)
    again = await ingestion.backfill(db_session, adapter, btc, Timeframe.H1, SINCE, now=NOW)
    assert (again.fetched, again.written) == (48, 0)
    assert await _count(db_session) == 48


class _SpyAdapter:
    """Delega en `FakeAdapter` y registra los rangos pedidos."""

    def __init__(self, inner: FakeAdapter) -> None:
        self.provider = inner.provider
        self._inner = inner
        self.calls: list[tuple[datetime, datetime]] = []

    async def fetch_ohlcv(
        self, instrument: InstrumentSchema, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[CandleSchema]:
        self.calls.append((start, end))
        return await self._inner.fetch_ohlcv(instrument, timeframe, start, end)


async def test_incremental_trae_lo_nuevo_y_repide_la_ultima(db_session: AsyncSession) -> None:
    btc = await instruments_repo.get_by_symbol(db_session, "BTC/USDT")
    assert btc is not None
    await ingestion.backfill(
        db_session, FakeAdapter(seed=1, now=_clock), btc, Timeframe.H1, SINCE, now=NOW
    )
    later = NOW + timedelta(hours=3)
    spy = _SpyAdapter(FakeAdapter(seed=1, now=lambda: later))
    result = await ingestion.incremental(db_session, spy, btc, Timeframe.H1, now=later)
    last_stored = NOW - timedelta(hours=1)
    assert spy.calls == [(last_stored, later)]
    assert result.fetched == 4  # la última guardada + 3 nuevas
    assert result.written == 3  # la repetida no cambia
    assert result.first_ts == last_stored
    assert result.last_ts == later - timedelta(hours=1)
    assert await _count(db_session) == 51


async def test_incremental_sin_datos_cae_al_backfill_por_defecto(db_session: AsyncSession) -> None:
    btc = await instruments_repo.get_by_symbol(db_session, "BTC/USDT")
    assert btc is not None
    spy = _SpyAdapter(FakeAdapter(seed=1, now=_clock))
    result = await ingestion.incremental(db_session, spy, btc, Timeframe.D1, now=NOW)
    expected_since = ingestion.default_since(Timeframe.D1, NOW)
    assert spy.calls == [(expected_since, NOW)]
    assert expected_since == NOW - timedelta(days=5 * 365)
    assert result.fetched == result.written > 1000
    assert await _count(db_session) == result.written


async def test_cli_all_recorre_4_instrumentos_por_5_timeframes(
    sessionmaker: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    capsys: pytest.CaptureFixture[str],
) -> None:
    since = (NOW - timedelta(days=2)).date().isoformat()
    code = await run(
        ["backfill", "--all", "--since", since],
        sessionmaker=sessionmaker,
        adapter_factory=_fake,
        clock=_clock,
    )
    assert code == 0
    stmt = select(OhlcvBar.instrument_id, OhlcvBar.timeframe).distinct()
    combos = (await db_session.execute(stmt)).all()
    assert len(combos) == 20
    assert "20 de 20" in capsys.readouterr().out


async def test_cli_incremental_symbol_tf(
    sessionmaker: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
) -> None:
    args = ["backfill", "--symbol", "BTC/USDT", "--tf", "1h", "--since", "2026-02-27"]
    assert await run(args, sessionmaker=sessionmaker, adapter_factory=_fake, clock=_clock) == 0
    before = await _count(db_session)
    assert before > 0
    inc = ["incremental", "--symbol", "BTC/USDT", "--tf", "1h"]
    assert await run(inc, sessionmaker=sessionmaker, adapter_factory=_fake, clock=_clock) == 0
    assert await _count(db_session) == before


class _FailingAdapter:
    provider = FakeAdapter().provider

    async def fetch_ohlcv(
        self, instrument: InstrumentSchema, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[CandleSchema]:
        raise MarketDataError("proveedor caído")


async def test_cli_un_fallo_no_impide_procesar_el_resto(
    sessionmaker: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def factory(instrument: InstrumentSchema) -> FakeAdapter | _FailingAdapter:
        return _FailingAdapter() if instrument.symbol == "EUR/USD" else _fake(instrument)

    code = await run(
        ["backfill", "--all", "--tf", "1h", "--since", "2026-02-27"],
        sessionmaker=sessionmaker,
        adapter_factory=factory,
        clock=_clock,
    )
    assert code == 1
    out = capsys.readouterr().out
    assert "Falló la ingesta de EUR/USD 1h: proveedor caído" in out
    assert "3 de 4 ingestas correctas, 1 con error" in out
    rows = await instruments_repo.list_all(db_session)
    stored = {
        r.symbol: (
            await db_session.execute(
                select(func.count()).select_from(OhlcvBar).where(OhlcvBar.instrument_id == r.id)
            )
        ).scalar_one()
        for r in rows
    }
    assert stored["EUR/USD"] == 0
    assert all(n > 0 for s, n in stored.items() if s != "EUR/USD")


async def test_cli_sin_datos_lo_dice(
    sessionmaker: async_sessionmaker[AsyncSession], capsys: pytest.CaptureFixture[str]
) -> None:
    # `until` implícito = now: una ventana vacía no descarga nada y debe avisarse.
    code = await run(
        ["backfill", "--symbol", "BTC/USDT", "--tf", "1d", "--since", "2026-03-01T11:00:00"],
        sessionmaker=sessionmaker,
        adapter_factory=_fake,
        clock=_clock,
    )
    assert code == 0
    assert "no se descargó ninguna vela" in capsys.readouterr().out


async def test_cli_simbolo_desconocido(
    sessionmaker: async_sessionmaker[AsyncSession], capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["incremental", "--symbol", "XYZ", "--tf", "1h"]
    code = await run(args, sessionmaker=sessionmaker, adapter_factory=_fake, clock=_clock)
    assert code == 1
    assert "Instrumento desconocido: XYZ" in capsys.readouterr().out


async def test_cli_oanda_sin_token_falla_con_mensaje_claro(
    sessionmaker: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Tras 0005 EUR/USD es de YAHOO; se devuelve temporalmente a OANDA para probar ese adaptador.
    swap = "UPDATE instruments SET provider = '{}' WHERE symbol = 'EUR/USD'"
    await db_session.execute(text(swap.format("OANDA")))
    await db_session.commit()
    try:
        settings = get_settings().model_copy(update={"oanda_api_token": None})
        args = ["incremental", "--symbol", "EUR/USD", "--tf", "1h"]
        code = await run(args, sessionmaker=sessionmaker, clock=_clock, settings=settings)
    finally:
        await db_session.execute(text(swap.format("YAHOO")))
        await db_session.commit()
    assert code == 1
    out = capsys.readouterr().out
    assert "Falta OANDA_API_TOKEN" in out
    assert "Traceback" not in out


# --- Yahoo (4.1, 4.2): descargador falso con los fixtures, sin red ---------------------------

_YAHOO_FIXTURES = {
    "5m": "yahoo_eurusd_5m.json",
    "15m": "yahoo_nas100_15m.json",
    "1h": "yahoo_eurusd_1h.json",
    "1d": "yahoo_xauusd_1d.json",
}
INTRADAY_NOW = datetime(2024, 1, 10, tzinfo=UTC)
DAILY_NOW = datetime(2024, 3, 20, tzinfo=UTC)


def _fixture_downloader(ticker: str, interval: str, start: datetime, end: datetime) -> pd.DataFrame:
    return frame_from_fixture(_YAHOO_FIXTURES[interval])


async def test_backfill_de_los_5_timeframes_de_un_instrumento_yahoo(
    db_session: AsyncSession,
) -> None:
    eur = await instruments_repo.get_by_symbol(db_session, "EUR/USD")
    assert eur is not None and eur.provider == "YAHOO"
    # (timeframe, ahora, desde, velas esperadas); los fixtures cubren fechas distintas.
    plan = [
        (Timeframe.M5, INTRADAY_NOW, datetime(2024, 1, 8, tzinfo=UTC), 6),
        (Timeframe.M15, INTRADAY_NOW, datetime(2024, 1, 8, tzinfo=UTC), 6),
        (Timeframe.H1, INTRADAY_NOW, datetime(2024, 1, 5, tzinfo=UTC), 25),
        (
            Timeframe.H4,
            INTRADAY_NOW,
            datetime(2024, 1, 5, 12, tzinfo=UTC),
            8,
        ),  # con parciales (D31)
        (Timeframe.D1, DAILY_NOW, datetime(2024, 3, 1, tzinfo=UTC), 4),
    ]
    for tf, now, since, expected in plan:
        adapter = YahooAdapter(_fixture_downloader, now=lambda n=now: n)
        result = await ingestion.backfill(db_session, adapter, eur, tf, since, now=now)
        assert (result.fetched, result.written) == (expected, expected), tf
        # El 4h del fixture tiene 3 bloques parciales (D31, D49); el resto no avisa nada.
        assert len(result.notices) == (1 if tf is Timeframe.H4 else 0), tf
        again = await ingestion.backfill(db_session, adapter, eur, tf, since, now=now)
        assert (again.fetched, again.written) == (expected, 0), tf
    combos = (
        await db_session.execute(select(OhlcvBar.timeframe).distinct().order_by(OhlcvBar.timeframe))
    ).scalars()
    assert sorted(combos) == sorted(t.value for t in Timeframe)


async def test_backfill_yahoo_informa_de_historia_recortada(db_session: AsyncSession) -> None:
    eur = await instruments_repo.get_by_symbol(db_session, "EUR/USD")
    assert eur is not None
    adapter = YahooAdapter(_fixture_downloader, now=lambda: INTRADAY_NOW)
    since = INTRADAY_NOW - timedelta(days=365)
    result = await ingestion.backfill(
        db_session, adapter, eur, Timeframe.M5, since, now=INTRADAY_NOW
    )
    assert result.notices
    assert "5m" in result.notices[0] and "59 días" in result.notices[0]
    # Un backfill posterior sin recorte limpia el aviso (se reinicia en cada llamada).
    ok = await ingestion.backfill(
        db_session, adapter, eur, Timeframe.M5, datetime(2024, 1, 8, tzinfo=UTC), now=INTRADAY_NOW
    )
    assert ok.notices == []


async def test_otros_adaptadores_no_tienen_aviso(db_session: AsyncSession) -> None:
    btc = await instruments_repo.get_by_symbol(db_session, "BTC/USDT")
    assert btc is not None
    result = await ingestion.backfill(
        db_session, FakeAdapter(seed=1, now=_clock), btc, Timeframe.H1, SINCE, now=NOW
    )
    assert result.notices == []


async def test_incremental_sin_datos_usa_el_horizonte_de_yahoo(db_session: AsyncSession) -> None:
    eur = await instruments_repo.get_by_symbol(db_session, "EUR/USD")
    assert eur is not None
    calls: list[tuple[str, datetime]] = []

    def downloader(ticker: str, interval: str, start: datetime, end: datetime) -> pd.DataFrame:
        calls.append((interval, start))
        return frame_from_fixture(_YAHOO_FIXTURES[interval])

    adapter = YahooAdapter(downloader, now=lambda: INTRADAY_NOW)
    result = await ingestion.incremental(db_session, adapter, eur, Timeframe.M5, now=INTRADAY_NOW)
    assert calls == [("5m", INTRADAY_NOW - timedelta(days=59))]
    assert result.notices == []


async def test_cli_avisa_de_historia_recortada(
    sessionmaker: async_sessionmaker[AsyncSession], capsys: pytest.CaptureFixture[str]
) -> None:
    def factory(_: InstrumentSchema) -> YahooAdapter:
        return YahooAdapter(_fixture_downloader, now=lambda: INTRADAY_NOW)

    code = await run(
        ["backfill", "--symbol", "EUR/USD", "--tf", "5m", "--since", "2023-01-01"],
        sessionmaker=sessionmaker,
        adapter_factory=factory,
        clock=lambda: INTRADAY_NOW,
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "aviso_ingesta" in out
    assert "Yahoo solo ofrece 59 días de historia en 5m" in out


async def test_cli_all_omite_nas100_1h_y_4h_con_aviso(
    sessionmaker: async_sessionmaker[AsyncSession], capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[tuple[str, str]] = []

    def downloader(ticker: str, interval: str, start: datetime, end: datetime) -> pd.DataFrame:
        calls.append((ticker, interval))
        return frame_from_fixture(_YAHOO_FIXTURES[interval])

    def factory(inst: InstrumentSchema) -> MarketDataAdapter:
        if inst.provider is Provider.YAHOO:
            return YahooAdapter(downloader, now=lambda: INTRADAY_NOW)
        return FakeAdapter(seed=1, now=_clock)

    code = await run(
        ["backfill", "--symbol", "NAS100", "--tf", "1h", "--since", "2024-01-05"],
        sessionmaker=sessionmaker,
        adapter_factory=factory,
        clock=lambda: INTRADAY_NOW,
    )
    out = capsys.readouterr().out
    assert code == 1 and calls == []
    assert "no soportado" in out and "alineadas a :30" in out
    assert "1 con error" in out

    code = await run(
        ["backfill", "--all", "--tf", "1h", "--since", "2024-01-05"],
        sessionmaker=sessionmaker,
        adapter_factory=factory,
        clock=lambda: INTRADAY_NOW,
    )
    out = capsys.readouterr().out
    assert "ingesta_omitida" in out and "NAS100 1h: omitido" in out
    assert not any(t == "^NDX" for t, _ in calls)
    assert code == 0 and "ingesta_fallida" not in out
    assert "1 omitidas (no soportadas)" in out
