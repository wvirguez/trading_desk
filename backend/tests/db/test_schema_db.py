"""Tests de esquema contra PostgreSQL + TimescaleDB reales (seed, hypertable, CHECK)."""

import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.repositories import instruments as instruments_repo
from app.schemas.enums import AssetClass, Provider, SessionType

pytestmark = pytest.mark.db

BACKEND_DIR = Path(__file__).resolve().parents[2]

EXPECTED = {
    "BTC/USDT": (
        AssetClass.CRYPTO, Provider.BINANCE, "BTC/USDT", "BTC", "USDT",
        Decimal("0.01"), Decimal("0.00001"), SessionType.CRYPTO_24_7,
    ),
    "EUR/USD": (
        AssetClass.FX, Provider.OANDA, "EUR_USD", "EUR", "USD",
        Decimal("0.00001"), Decimal("1"), SessionType.FX_24_5,
    ),
    "XAU/USD": (
        AssetClass.METAL, Provider.OANDA, "XAU_USD", "XAU", "USD",
        Decimal("0.001"), Decimal("1"), SessionType.FX_24_5,
    ),
    "NAS100": (
        AssetClass.INDEX, Provider.OANDA, "NAS100_USD", "NAS100", "USD",
        Decimal("0.1"), Decimal("0.1"), SessionType.INDEX_CFD,
    ),
}  # fmt: skip


async def _instrument_id(session: AsyncSession, symbol: str = "BTC/USDT") -> int:
    row = await instruments_repo.get_by_symbol(session, symbol)
    assert row is not None
    return row.id


async def test_seed_deja_los_cuatro_instrumentos(db_session: AsyncSession) -> None:
    rows = await instruments_repo.list_all(db_session)
    schemas = {r.symbol: instruments_repo.to_schema(r) for r in rows}
    assert set(schemas) == set(EXPECTED)
    assert len(rows) == 4
    for symbol, (ac, prov, psym, base, quote, tick, lot, sess) in EXPECTED.items():
        s = schemas[symbol]
        assert (s.asset_class, s.provider, s.provider_symbol) == (ac, prov, psym)
        assert (s.base_currency, s.quote_currency) == (base, quote)
        assert (s.tick_size, s.lot_size, s.session) == (tick, lot, sess)


async def test_ohlcv_bars_es_hypertable(db_session: AsyncSession) -> None:
    result = await db_session.execute(
        text(
            "SELECT h.num_dimensions, d.time_interval FROM timescaledb_information.hypertables h "
            "JOIN timescaledb_information.dimensions d USING (hypertable_schema, hypertable_name) "
            "WHERE h.hypertable_name = 'ohlcv_bars'"
        )
    )
    rows = result.all()
    assert len(rows) == 1
    assert rows[0].time_interval.days == 30


async def test_check_ohlc_rechaza_fila_incoherente(db_session: AsyncSession) -> None:
    instrument_id = await _instrument_id(db_session)
    with pytest.raises(IntegrityError, match="ck_ohlcv_bars_ohlc"):
        await db_session.execute(
            text(
                "INSERT INTO ohlcv_bars (instrument_id, timeframe, ts, open, high, low, close, "
                "volume) VALUES (:i, '1h', '2026-01-01T00:00:00Z', 100, 90, 95, 98, 1)"
            ),
            {"i": instrument_id},
        )


async def test_trade_signal_nace_pending(db_session: AsyncSession) -> None:
    instrument_id = await _instrument_id(db_session)
    result = await db_session.execute(
        text(
            "INSERT INTO trade_signals (instrument_id, timeframe, direction, entry, stop_loss, "
            "take_profit) VALUES (:i, '1h', 'LONG', 100, 95, 110) RETURNING id, status"
        ),
        {"i": instrument_id},
    )
    row = result.one()
    assert row.status == "PENDING"
    assert row.id is not None


async def test_trade_signal_rechaza_status_desconocido(db_session: AsyncSession) -> None:
    instrument_id = await _instrument_id(db_session)
    with pytest.raises(IntegrityError, match="ck_trade_signals_status"):
        await db_session.execute(
            text(
                "INSERT INTO trade_signals (instrument_id, timeframe, direction, entry, "
                "stop_loss, take_profit, status) VALUES (:i, '1h', 'LONG', 100, 95, 110, 'FOO')"
            ),
            {"i": instrument_id},
        )


def test_downgrade_base_y_upgrade_head() -> None:
    """Ejecuta Alembic en un subproceso contra la BD de test (Settings lee DATABASE_URL)."""
    env = {**os.environ, "DATABASE_URL": get_settings().test_database_url}
    for args in (["downgrade", "base"], ["upgrade", "head"]):
        proc = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "alembic", *args],
            cwd=BACKEND_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert proc.returncode == 0, f"alembic {' '.join(args)} falló:\n{proc.stderr}"
