"""Tests `db` de `agent_analyses`: migración, CHECK, JSONB, solo inserción y repositorio."""

import os
import subprocess
import sys
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.agent_analysis import StepStatus
from app.repositories import agent_analyses as repo
from app.repositories import instruments as instruments_repo
from app.schemas.enums import AnalysisStep, Timeframe

pytestmark = pytest.mark.db

BACKEND_DIR = Path(__file__).resolve().parents[2]

_RAW_INSERT = (
    "INSERT INTO agent_analyses (analysis_id, step, instrument_id, timeframe, input, "
    "input_tokens, output_tokens, latency_ms, status) VALUES "
    "(uuid_generate_v4(), :step, :i, :tf, '{}', 0, 0, 0, :st)"
)


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
    analysis_id: uuid.UUID | None = None,
    step: AnalysisStep = AnalysisStep.STRUCTURE,
    **kwargs: Any,
) -> Any:
    return await repo.insert_step(
        session,
        analysis_id=analysis_id or uuid.uuid4(),
        step=step,
        instrument_id=await _btc_id(session),
        timeframe=Timeframe.H1,
        input=kwargs.pop("input", {"ctx": 1}),
        **kwargs,
    )


async def test_tabla_e_indices_existen_en_head(db_session: AsyncSession) -> None:
    exists = (
        await db_session.execute(text("SELECT to_regclass('public.agent_analyses')"))
    ).scalar()
    assert exists == "agent_analyses"
    defs = (
        await db_session.execute(
            text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'agent_analyses'")
        )
    ).all()
    by_name = {r.indexname: r.indexdef for r in defs}
    assert "(analysis_id)" in by_name["ix_agent_analyses_analysis_id"]
    assert "created_at DESC" in by_name["ix_agent_analyses_instrument_id_created_at"]


async def test_insert_step_devuelve_id_y_created_at(db_session: AsyncSession) -> None:
    row = await _insert(db_session)
    assert row.id is not None
    assert row.created_at is not None
    assert row.status == "OK"
    assert row.step == "STRUCTURE"


async def test_jsonb_round_trip_y_cost_decimal(db_session: AsyncSession) -> None:
    inp = {"niveles": [1.5, 2], "anidado": {"a": [1, None]}, "ok": True}
    out = {"bias": "BULLISH", "lista": ["x"]}
    trace = {"prompt_version": "v1", "messages": [{"role": "user", "parts": []}]}
    row = await _insert(
        db_session,
        input=inp,
        output=out,
        trace=trace,
        model="m",
        input_tokens=10,
        output_tokens=5,
        cost_usd=Decimal("0.00012345"),
        latency_ms=120,
    )
    row_id = row.id
    await db_session.commit()
    db_session.expire_all()
    got = (
        await db_session.execute(
            text("SELECT input, output, trace, cost_usd FROM agent_analyses WHERE id = :i"),
            {"i": row_id},
        )
    ).one()
    assert (got.input, got.output, got.trace) == (inp, out, trace)
    assert got.cost_usd == Decimal("0.00012345")


@pytest.mark.parametrize(
    ("step", "tf", "st", "constraint"),
    [
        ("FOO", "1h", "OK", "ck_agent_analyses_step"),
        ("QUANT", "2m", "OK", "ck_agent_analyses_timeframe"),
        ("QUANT", "1h", "MAL", "ck_agent_analyses_status"),
    ],
)
async def test_check_rechaza_valores_invalidos(
    db_session: AsyncSession, step: str, tf: str, st: str, constraint: str
) -> None:
    iid = await _btc_id(db_session)
    with pytest.raises(IntegrityError, match=constraint):
        await db_session.execute(text(_RAW_INSERT), {"step": step, "i": iid, "tf": tf, "st": st})


async def test_update_y_delete_lanzan_error_y_el_insert_sigue(db_session: AsyncSession) -> None:
    row = await _insert(db_session)
    row_id = row.id
    await db_session.commit()
    with pytest.raises(DBAPIError, match="agent_analyses es de solo inserción"):
        await db_session.execute(
            text("UPDATE agent_analyses SET model = 'x' WHERE id = :i"), {"i": row_id}
        )
    await db_session.rollback()
    with pytest.raises(DBAPIError, match="agent_analyses es de solo inserción"):
        await db_session.execute(text("DELETE FROM agent_analyses WHERE id = :i"), {"i": row_id})
    await db_session.rollback()
    await _insert(db_session, step=AnalysisStep.QUANT)
    await db_session.commit()
    n = (await db_session.execute(text("SELECT count(*) FROM agent_analyses"))).scalar()
    assert n == 2


async def test_list_by_analysis_ordena_por_created_at(db_session: AsyncSession) -> None:
    aid = uuid.uuid4()
    steps = [AnalysisStep.STRUCTURE, AnalysisStep.QUANT, AnalysisStep.PROPOSAL, AnalysisStep.GUARDS]
    for step in steps:
        await _insert(db_session, analysis_id=aid, step=step)
    await _insert(db_session, step=AnalysisStep.RISK_AUDIT)  # otro análisis
    rows = await repo.list_by_analysis(db_session, aid)
    assert [r.step for r in rows] == [s.value for s in steps]
    assert await repo.list_by_analysis(db_session, uuid.uuid4()) == []


async def test_insert_step_error_guarda_status_y_mensaje(db_session: AsyncSession) -> None:
    row = await _insert(db_session, status=StepStatus.ERROR, error="boom")
    assert (row.status, row.error, row.output) == ("ERROR", "boom", None)


async def test_downgrade_y_upgrade_de_0007(db_session: AsyncSession) -> None:
    await db_session.commit()
    try:
        _alembic("downgrade", "0006_strategies")
        await db_session.rollback()
        exists = (
            await db_session.execute(text("SELECT to_regclass('public.agent_analyses')"))
        ).scalar()
        assert exists is None
        fn = (
            await db_session.execute(
                text("SELECT count(*) FROM pg_proc WHERE proname = 'agent_analyses_append_only'")
            )
        ).scalar()
        assert fn == 0
        await db_session.rollback()
    finally:
        _alembic("upgrade", "head")
    exists = (
        await db_session.execute(text("SELECT to_regclass('public.agent_analyses')"))
    ).scalar()
    assert exists == "agent_analyses"


async def test_unique_analysis_id_step_rechaza_el_paso_repetido(db_session: AsyncSession) -> None:
    aid = uuid.uuid4()
    await _insert(db_session, analysis_id=aid, step=AnalysisStep.STRUCTURE)
    await _insert(db_session, analysis_id=aid, step=AnalysisStep.QUANT)  # otro paso: válido
    await _insert(db_session, step=AnalysisStep.STRUCTURE)  # otro análisis: válido
    with pytest.raises(IntegrityError, match="uq_agent_analyses_analysis_id_step"):
        await _insert(db_session, analysis_id=aid, step=AnalysisStep.STRUCTURE)
    await db_session.rollback()


async def test_downgrade_y_upgrade_de_0009(db_session: AsyncSession) -> None:
    await db_session.commit()
    iid = await _btc_id(db_session)
    await db_session.commit()  # suelta el bloqueo de lectura sobre `instruments` (0010 lo necesita)
    aid = uuid.uuid4()
    params = {"a": aid, "i": iid}
    raw = _RAW_INSERT.replace("uuid_generate_v4()", ":a").replace(":step", "'STRUCTURE'")
    raw = raw.replace(":tf", "'1h'").replace(":st", "'OK'")
    try:
        _alembic("downgrade", "0008_trade_signals_analysis")
        await db_session.rollback()
        for _ in range(2):  # sin la restricción, el duplicado ya se admite
            await db_session.execute(text(raw), params)
        await db_session.commit()
    finally:
        # El duplicado impediría reaplicar la restricción y la tabla es de solo inserción:
        # se vacía con TRUNCATE (el trigger no lo bloquea) antes de volver a `head`.
        await db_session.rollback()
        await db_session.execute(text("TRUNCATE agent_analyses"))
        await db_session.commit()
        _alembic("upgrade", "head")
    await db_session.rollback()
    constraints = (
        (
            await db_session.execute(
                text(
                    "SELECT conname FROM pg_constraint WHERE conrelid = 'agent_analyses'::regclass"
                )
            )
        )
        .scalars()
        .all()
    )
    assert "uq_agent_analyses_analysis_id_step" in constraints
