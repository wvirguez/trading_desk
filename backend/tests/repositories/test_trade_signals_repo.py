"""Tests `db` de `trade_signals` ampliada (0008) y su repositorio."""

import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.repositories import instruments as instruments_repo
from app.repositories import trade_signals as repo
from app.schemas.enums import (
    AssetClass,
    Direction,
    RegimeLabel,
    SignalStatus,
    Timeframe,
    VetoReason,
)
from app.schemas.risk import PositionSizeResult
from app.schemas.signals import AUDITOR_REJECTION_MARKER, TradeSignalSchema

pytestmark = pytest.mark.db

BACKEND_DIR = Path(__file__).resolve().parents[2]
T0 = datetime(2026, 11, 1, tzinfo=UTC)

NEW_COLUMNS = {"analysis_id", "rr", "units", "risk_amount", "regime", "rationale", "veto_reasons"}


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


async def _iid(session: AsyncSession, symbol: str = "BTC/USDT") -> int:
    row = await instruments_repo.get_by_symbol(session, symbol)
    assert row is not None
    return row.id


def _signal(
    symbol: str = "BTC/USDT",
    status: SignalStatus = SignalStatus.APPROVED,
    created_at: datetime = T0,
    veto: list[VetoReason] | None = None,
    rationale: str = "motivo",
) -> TradeSignalSchema:
    approved = status is SignalStatus.APPROVED
    return TradeSignalSchema(
        id=uuid.uuid4(),
        analysis_id=uuid.uuid4(),
        symbol=symbol,
        asset_class=AssetClass.CRYPTO,
        timeframe=Timeframe.H1,
        direction=Direction.LONG,
        entry=Decimal("100.5"),
        stop_loss=Decimal("95.25"),
        take_profit=Decimal("111.0"),
        rr=Decimal("2.0000"),
        size=(
            PositionSizeResult(
                units=Decimal("1.9047619048"),
                risk_amount=Decimal("100.0000000000"),
                risk_pct=Decimal("1"),
                stop_distance=Decimal("5.25"),
                notional=Decimal("191.4285714324"),
            )
            if approved
            else None
        ),
        status=status,
        regime=RegimeLabel.TRENDING,
        rationale=rationale,
        veto_reasons=veto or [],
        created_at=created_at,
    )


async def test_columnas_nuevas_e_indice_en_head(db_session: AsyncSession) -> None:
    cols = (
        await db_session.execute(
            text(
                "SELECT column_name, is_nullable FROM information_schema.columns "
                "WHERE table_name = 'trade_signals'"
            )
        )
    ).all()
    nullable = {c.column_name: c.is_nullable for c in cols}
    assert NEW_COLUMNS <= set(nullable)
    assert nullable["veto_reasons"] == "NO"
    assert all(nullable[c] == "YES" for c in NEW_COLUMNS - {"veto_reasons"})
    idx = (
        await db_session.execute(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_trade_signals_analysis_id'")
        )
    ).scalar_one()
    assert "(analysis_id)" in idx


async def test_check_rechaza_regime_invalido(db_session: AsyncSession) -> None:
    iid = await _iid(db_session)
    with pytest.raises(IntegrityError, match="ck_trade_signals_regime"):
        await db_session.execute(
            text(
                "INSERT INTO trade_signals (instrument_id, timeframe, direction, entry, "
                "stop_loss, take_profit, regime) VALUES (:i, '1h', 'LONG', 100, 95, 110, 'X')"
            ),
            {"i": iid},
        )


async def test_fila_antigua_sigue_valida(db_session: AsyncSession) -> None:
    iid = await _iid(db_session)
    row = (
        await db_session.execute(
            text(
                "INSERT INTO trade_signals (instrument_id, timeframe, direction, entry, "
                "stop_loss, take_profit) VALUES (:i, '1h', 'LONG', 100, 95, 110) "
                "RETURNING status, analysis_id, regime, rr, veto_reasons"
            ),
            {"i": iid},
        )
    ).one()
    assert (row.status, row.analysis_id, row.regime, row.rr) == ("PENDING", None, None, None)
    assert row.veto_reasons == []


async def test_insert_signal_round_trip(db_session: AsyncSession) -> None:
    iid = await _iid(db_session)
    sig = _signal(
        status=SignalStatus.REJECTED,
        veto=[VetoReason.RR_BELOW_MIN, VetoReason.OPEN_RISK_LIMIT],
    )
    await repo.insert_signal(db_session, sig, iid)
    await db_session.commit()
    db_session.expire_all()
    raw = (
        await db_session.execute(
            text("SELECT veto_reasons, rr, units FROM trade_signals WHERE id = :i"),
            {"i": sig.id},
        )
    ).one()
    assert raw.veto_reasons == ["RR_BELOW_MIN", "OPEN_RISK_LIMIT"]
    assert raw.rr == Decimal("2.0000")
    assert raw.units is None


async def test_approved_round_trip_via_list_active(db_session: AsyncSession) -> None:
    iid = await _iid(db_session)
    sig = _signal()
    await repo.insert_signal(db_session, sig, iid)
    [got] = await repo.list_active(db_session, None, 10)
    assert got.id == sig.id
    assert got.analysis_id == sig.analysis_id
    assert (got.symbol, got.asset_class, got.status) == ("BTC/USDT", AssetClass.CRYPTO, sig.status)
    assert (got.entry, got.stop_loss, got.take_profit) == (
        sig.entry,
        sig.stop_loss,
        sig.take_profit,
    )
    assert got.rr == sig.rr
    assert got.size is not None
    assert got.size.units == Decimal("1.9047619048")
    assert got.size.risk_amount == Decimal("100")
    assert got.size.stop_distance == Decimal("5.25")
    assert got.size.risk_pct == Decimal("1")  # 100 / 10 000 * 100
    assert got.regime is RegimeLabel.TRENDING
    assert got.created_at == T0


async def test_rechazo_del_auditor_se_reconstruye(db_session: AsyncSession) -> None:
    iid = await _iid(db_session)
    sig = _signal(status=SignalStatus.REJECTED, rationale=f"{AUDITOR_REJECTION_MARKER} dudas")
    row = await repo.insert_signal(db_session, sig, iid)
    instrument = await instruments_repo.get_by_symbol(db_session, "BTC/USDT")
    assert instrument is not None
    assert repo.to_schema(row, instrument) == sig


async def test_to_schema_rechaza_fila_antigua(db_session: AsyncSession) -> None:
    iid = await _iid(db_session)
    await db_session.execute(
        text(
            "INSERT INTO trade_signals (instrument_id, timeframe, direction, entry, stop_loss, "
            "take_profit, status) VALUES (:i, '1h', 'LONG', 100, 95, 110, 'APPROVED')"
        ),
        {"i": iid},
    )
    # Una APPROVED antigua sin datos de la Fase 3 no se lista (no se puede reconstruir).
    assert await repo.list_active(db_session, None, 10) == []


async def test_list_active_solo_approved_orden_filtro_y_limit(db_session: AsyncSession) -> None:
    btc, eur = await _iid(db_session), await _iid(db_session, "EUR/USD")
    older = _signal(created_at=T0)
    newer = _signal(created_at=T0 + timedelta(hours=2))
    middle = _signal(created_at=T0 + timedelta(hours=1))
    rejected = _signal(
        status=SignalStatus.REJECTED,
        created_at=T0 + timedelta(hours=3),
        veto=[VetoReason.RR_BELOW_MIN],
    )
    for s in (older, newer, middle, rejected):
        await repo.insert_signal(db_session, s, btc)
    fx = _signal(symbol="EUR/USD", created_at=T0 + timedelta(hours=4))
    await repo.insert_signal(db_session, fx, eur)

    all_ids = [s.id for s in await repo.list_active(db_session, None, 50)]
    assert all_ids == [fx.id, newer.id, middle.id, older.id]  # sin la REJECTED

    crypto = await repo.list_active(db_session, AssetClass.CRYPTO, 50)
    assert [s.id for s in crypto] == [newer.id, middle.id, older.id]
    fx_only = await repo.list_active(db_session, AssetClass.FX, 50)
    assert [s.id for s in fx_only] == [fx.id]
    assert await repo.list_active(db_session, AssetClass.METAL, 50) == []

    assert [s.id for s in await repo.list_active(db_session, None, 2)] == [fx.id, newer.id]


async def test_downgrade_y_upgrade_de_0008(db_session: AsyncSession) -> None:
    iid = await _iid(db_session)
    await db_session.execute(
        text(
            "INSERT INTO trade_signals (instrument_id, timeframe, direction, entry, stop_loss, "
            "take_profit) VALUES (:i, '1h', 'LONG', 100, 95, 110)"
        ),
        {"i": iid},
    )
    await db_session.commit()
    try:
        _alembic("downgrade", "0007_agent_analyses")
        await db_session.rollback()
        cols = {
            r.column_name
            for r in await db_session.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'trade_signals'"
                )
            )
        }
        assert not NEW_COLUMNS & cols
        n = (await db_session.execute(text("SELECT count(*) FROM trade_signals"))).scalar()
        assert n == 1  # la fila antigua se conserva
        await db_session.rollback()
    finally:
        _alembic("upgrade", "head")
    cols = {
        r.column_name
        for r in await db_session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'trade_signals'"
            )
        )
    }
    assert NEW_COLUMNS <= cols
