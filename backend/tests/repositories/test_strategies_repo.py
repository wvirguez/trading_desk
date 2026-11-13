"""Tests `db` de `strategies`: migración, CHECK, JSONB y repositorio."""

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.repositories import instruments as instruments_repo
from app.repositories import strategies as repo
from app.schemas.enums import Timeframe

pytestmark = pytest.mark.db

BACKEND_DIR = Path(__file__).resolve().parents[2]
D_FROM = datetime(2026, 1, 1, tzinfo=UTC)
D_TO = datetime(2026, 2, 1, tzinfo=UTC)


def _alembic(*args: str) -> None:
    env = {**os.environ, "DATABASE_URL": get_settings().test_database_url}
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


async def _btc_id(session: AsyncSession) -> int:
    row = await instruments_repo.get_by_symbol(session, "BTC/USDT")
    assert row is not None
    return row.id


async def _insert(
    session: AsyncSession,
    params: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
) -> Any:
    return await repo.insert_strategy(
        session,
        name="zscore_mean_reversion",
        instrument_id=await _btc_id(session),
        timeframe=Timeframe.H1,
        params=params or {"zscore_window": 20},
        metrics=metrics or {"sharpe": 1.5},
        config_hash="abc123",
        data_from=D_FROM,
        data_to=D_TO,
    )


async def test_tabla_strategies_existe_en_head(db_session: AsyncSession) -> None:
    exists = (await db_session.execute(text("SELECT to_regclass('public.strategies')"))).scalar()
    assert exists == "strategies"
    idx = (
        await db_session.execute(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = :n"),
            {"n": "ix_strategies_instrument_id_created_at"},
        )
    ).scalar_one()
    assert "created_at DESC" in idx


async def test_insert_strategy_devuelve_id_y_created_at(db_session: AsyncSession) -> None:
    s = await _insert(db_session)
    assert s.id is not None
    assert s.created_at is not None
    assert s.timeframe == "1h"


async def test_jsonb_round_trip(db_session: AsyncSession) -> None:
    params = {"zscore_window": 20, "entry_z": 2.0, "allow_short": True, "anidado": {"a": [1, 2]}}
    metrics = {"sharpe": 1.234567, "n_trades": 7, "warnings": ["x"], "nulo": None}
    strategy_id = (await _insert(db_session, params, metrics)).id
    await db_session.commit()
    db_session.expire_all()
    row = (
        await db_session.execute(
            text("SELECT params, metrics FROM strategies WHERE id = :i"), {"i": strategy_id}
        )
    ).one()
    assert row.params == params
    assert row.metrics == metrics


async def test_check_rechaza_timeframe_invalido(db_session: AsyncSession) -> None:
    iid = await _btc_id(db_session)
    with pytest.raises(IntegrityError, match="ck_strategies_timeframe"):
        await db_session.execute(
            text(
                "INSERT INTO strategies (name, instrument_id, timeframe, params, metrics, "
                "config_hash, data_from, data_to) VALUES ('n', :i, '2m', '{}', '{}', 'h', "
                "now(), now())"
            ),
            {"i": iid},
        )


async def test_downgrade_y_upgrade_de_0006(db_session: AsyncSession) -> None:
    await db_session.commit()
    try:
        _alembic("downgrade", "-1")
        await db_session.rollback()
        exists = (
            await db_session.execute(text("SELECT to_regclass('public.strategies')"))
        ).scalar()
        assert exists is None
        await db_session.rollback()
    finally:
        _alembic("upgrade", "head")
    exists = (await db_session.execute(text("SELECT to_regclass('public.strategies')"))).scalar()
    assert exists == "strategies"
