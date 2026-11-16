"""Tests `db` de la migración 0010 (`paper_orders`): tabla, CHECK, índices y UNIQUE."""

import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings

pytestmark = pytest.mark.db

BACKEND_DIR = Path(__file__).resolve().parents[2]

COLUMNS = {
    "id", "signal_id", "instrument_id", "timeframe", "direction", "units", "signal_entry",
    "stop_loss", "take_profit", "risk_amount", "status", "executed_at", "fill_price",
    "exit_price", "realized_pnl", "filled_at", "closed_at", "last_processed_ts", "created_at",
    "updated_at",
}  # fmt: skip


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


async def _signal_id(session: AsyncSession) -> tuple[uuid.UUID, int]:
    iid = (
        await session.execute(text("SELECT id FROM instruments WHERE symbol = 'BTC/USDT'"))
    ).scalar_one()
    sid = (
        await session.execute(
            text(
                "INSERT INTO trade_signals (instrument_id, timeframe, direction, entry, "
                "stop_loss, take_profit) VALUES (:i, '1h', 'LONG', 100, 95, 110) RETURNING id"
            ),
            {"i": iid},
        )
    ).scalar_one()
    return sid, iid


async def _insert(
    session: AsyncSession, sid: uuid.UUID, iid: int, status: str = "PENDING_FILL", **extra: object
) -> None:
    cols: dict[str, object] = dict.fromkeys(
        ("fill_price", "filled_at", "exit_price", "closed_at", "realized_pnl")
    )
    cols.update(extra)
    await session.execute(
        text(
            "INSERT INTO paper_orders (signal_id, instrument_id, timeframe, direction, units, "
            "signal_entry, stop_loss, take_profit, risk_amount, status, executed_at, "
            "fill_price, filled_at, exit_price, closed_at, realized_pnl) "
            "VALUES (:s, :i, '1h', 'LONG', 1, 100, 95, 110, 5, :st, now(), "
            "CAST(:fill_price AS numeric), CAST(:filled_at AS timestamptz), "
            "CAST(:exit_price AS numeric), CAST(:closed_at AS timestamptz), "
            "CAST(:realized_pnl AS numeric))"
        ),
        {"s": sid, "i": iid, "st": status, **cols},
    )


NOW = datetime(2026, 11, 16, tzinfo=UTC)


async def test_head_crea_tabla_indices_y_unique(db_session: AsyncSession) -> None:
    cols = {
        r.column_name
        for r in await db_session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'paper_orders'"
            )
        )
    }
    assert cols == COLUMNS
    indexes = {
        r.indexname: r.indexdef
        for r in await db_session.execute(
            text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'paper_orders'")
        )
    }
    assert "(status)" in indexes["ix_paper_orders_status"]
    assert "(closed_at)" in indexes["ix_paper_orders_closed_at"]
    assert "UNIQUE" in indexes["uq_paper_orders_signal_id"]
    assert "(signal_id)" in indexes["uq_paper_orders_signal_id"]


async def test_estados_coherentes_se_aceptan_y_status_por_defecto(
    db_session: AsyncSession,
) -> None:
    sid, iid = await _signal_id(db_session)
    await db_session.execute(
        text(
            "INSERT INTO paper_orders (signal_id, instrument_id, timeframe, direction, units, "
            "signal_entry, stop_loss, take_profit, risk_amount, executed_at) "
            "VALUES (:s, :i, '1h', 'LONG', 1, 100, 95, 110, 5, now())"
        ),
        {"s": sid, "i": iid},
    )
    row = (await db_session.execute(text("SELECT id, status FROM paper_orders"))).one()
    assert row.status == "PENDING_FILL"
    assert row.id is not None
    await db_session.execute(text("DELETE FROM paper_orders"))
    await _insert(db_session, sid, iid, "OPEN", fill_price="100", filled_at=NOW)
    await db_session.execute(text("DELETE FROM paper_orders"))
    await _insert(
        db_session, sid, iid, "CLOSED_TP",
        fill_price="100", filled_at=NOW, exit_price="110", closed_at=NOW, realized_pnl="10",
    )  # fmt: skip


@pytest.mark.parametrize(
    ("status", "extra"),
    [
        ("CLOSED_SL", {"fill_price": "100", "filled_at": NOW, "closed_at": NOW,
                       "realized_pnl": "-5"}),  # sin exit_price
        ("CLOSED_TP", {}),
        ("OPEN", {}),
        ("OPEN", {"fill_price": "100", "filled_at": NOW, "realized_pnl": "1"}),
        ("OPEN", {"fill_price": "100", "filled_at": NOW, "closed_at": NOW}),
        ("PENDING_FILL", {"fill_price": "100"}),
        ("PENDING_FILL", {"realized_pnl": "1"}),
    ],
)  # fmt: skip
async def test_check_rechaza_estado_incoherente(
    db_session: AsyncSession, status: str, extra: dict[str, object]
) -> None:
    sid, iid = await _signal_id(db_session)
    with pytest.raises(IntegrityError, match="ck_paper_orders_status_state"):
        await _insert(db_session, sid, iid, status, **extra)


async def test_check_rechaza_status_invalido(db_session: AsyncSession) -> None:
    sid, iid = await _signal_id(db_session)
    with pytest.raises(IntegrityError, match=r"ck_paper_orders_status\""):
        await _insert(db_session, sid, iid, "FOO")


async def test_unique_signal_id(db_session: AsyncSession) -> None:
    sid, iid = await _signal_id(db_session)
    await _insert(db_session, sid, iid)
    with pytest.raises(IntegrityError, match="uq_paper_orders_signal_id"):
        await _insert(db_session, sid, iid)


async def test_downgrade_elimina_y_upgrade_recrea(db_session: AsyncSession) -> None:
    await db_session.commit()
    try:
        _alembic("downgrade", "0009_agent_analyses_unique_step")
        exists = (
            await db_session.execute(text("SELECT to_regclass('public.paper_orders')"))
        ).scalar_one()
        assert exists is None
        await db_session.rollback()
    finally:
        _alembic("upgrade", "head")
    exists = (
        await db_session.execute(text("SELECT to_regclass('public.paper_orders')"))
    ).scalar_one()
    assert exists == "paper_orders"
