"""Tests de estructura de mercado con fixtures dibujados a mano (D55, D68)."""

import json
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import pytest

from app.quant.structure import analyze_structure, find_fvgs, find_swings
from app.schemas.enums import SwingKind
from app.schemas.quant import MarketStructureResult

FIXTURES = Path(__file__).parent.parent / "fixtures" / "structure"
CASES = sorted(p.stem for p in FIXTURES.glob("*.json"))


def _frame(rows: Sequence[tuple[float, float, float]]) -> pl.DataFrame:
    """Velas horarias desde 2026-01-01 a partir de tuplas (high, low, close)."""
    return pl.DataFrame(
        {
            "ts": [datetime(2026, 1, 1) + timedelta(hours=k) for k in range(len(rows))],
            "open": [float(r[2]) for r in rows],
            "high": [float(r[0]) for r in rows],
            "low": [float(r[1]) for r in rows],
            "close": [float(r[2]) for r in rows],
            "volume": [1.0] * len(rows),
        }
    ).with_columns(pl.col("ts").dt.replace_time_zone("UTC").cast(pl.Datetime("us", "UTC")))


def _load(name: str) -> tuple[int, pl.DataFrame, dict[str, Any]]:
    data = json.loads((FIXTURES / f"{name}.json").read_text())
    assert data["description"]
    c = data["candles"]
    df = pl.DataFrame(
        {
            "ts": [datetime.fromisoformat(x["ts"]) for x in c],
            **{k: [float(x[k]) for x in c] for k in ("open", "high", "low", "close", "volume")},
        }
    ).with_columns(pl.col("ts").cast(pl.Datetime("us", "UTC")))
    return int(data["n"]), df, data["expected"]


@pytest.mark.parametrize("name", CASES)
def test_fixture_exacto(name: str) -> None:
    n, df, expected = _load(name)
    result = analyze_structure(df, n)
    assert result == MarketStructureResult.model_validate(expected)


def test_hay_fixtures_esperados() -> None:
    assert len(CASES) == 7


def test_swings_alternos_y_confirmacion_n_velas_despues() -> None:
    n, df, _ = _load("swings_alternos")
    swings = find_swings(df, n)
    assert [s.kind for s in swings] == [SwingKind.HIGH, SwingKind.LOW] * 2
    ts = df["ts"].to_list()
    for s in swings:
        assert s.confirmed_at == ts[ts.index(s.ts) + n]


def test_sin_swings_con_menos_de_2n_mas_1_velas() -> None:
    rows = [(1.0 + (i % 2), 0.5, 1.0) for i in range(6)]
    assert find_swings(_frame(rows), 3) == []
    # Con exactamente 2n+1 velas sí puede haber un swing (vela central).
    rows7 = [
        (1, 0.5, 1),
        (2, 0.6, 1),
        (3, 0.7, 1),
        (9, 0.1, 1),
        (3, 0.7, 1),
        (2, 0.6, 1),
        (1, 0.5, 1),
    ]
    assert [s.kind for s in find_swings(_frame(rows7), 3)] == [SwingKind.HIGH, SwingKind.LOW]
    assert find_swings(_frame(rows7[:6]), 3) == []


def test_swing_alto_exige_maximo_estricto() -> None:
    # Empate de highs en 2 y 3: ninguno es swing alto con n=2.
    empate = [(1, 0.5, 1), (2, 0.5, 1), (3, 0.5, 1), (3, 0.5, 1), (1, 0.5, 1), (1, 0.5, 1)]
    assert find_swings(_frame(empate), 2) == []
    unico = [(1, 0.5, 1), (2, 0.5, 1), (3, 0.5, 1), (2.9, 0.5, 1), (1, 0.5, 1)]
    swings = find_swings(_frame(unico), 2)
    assert [(s.kind, str(s.price)) for s in swings] == [(SwingKind.HIGH, "3.0")]
    # Mínimo con empate: tampoco es swing bajo.
    bajo = [(5, 4, 5), (5, 3, 5), (5, 2, 5), (5, 2, 5), (5, 4, 5)]
    assert find_swings(_frame(bajo), 2) == []


def _random_walk_frame(size: int, seed: int) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1, size))
    spread = rng.uniform(0.1, 1.5, size)
    high = np.round(close + spread, 2)
    low = np.round(close - spread, 2)
    rows = [
        (float(h), float(lo), float(round(c, 2))) for h, lo, c in zip(high, low, close, strict=True)
    ]
    return _frame(rows)


@pytest.mark.parametrize("source", [*CASES, "random_walk"])
def test_truncado_no_cambia_lo_confirmado(source: str) -> None:
    if source == "random_walk":
        n, df = 3, _random_walk_frame(150, 7)
    else:
        n, df, _ = _load(source)
    full = analyze_structure(df, n)
    ts = df["ts"].to_list()
    for k in range(1, df.height + 1):
        cut = analyze_structure(df.head(k), n)
        last = ts[k - 1]
        assert cut.swings == [s for s in full.swings if s.confirmed_at <= last]
        assert cut.events == [e for e in full.events if e.ts <= last]
        # FVG: la vela central i exige i+1 <= k-1; la mitigación posterior a `last` aún no existe.
        esperados = [
            f.model_copy(update={"mitigated_at": None})
            if f.mitigated_at is not None and f.mitigated_at > last
            else f
            for f in full.fvgs
            if f.ts <= ts[max(k - 2, 0)] and k >= 3
        ]
        assert cut.fvgs == esperados


def test_random_walk_produce_estructura() -> None:
    result = analyze_structure(_random_walk_frame(150, 7), 3)
    assert result.swings and result.events and result.fvgs
    for seq in (result.swings, result.events, result.fvgs):
        stamps = [x.ts for x in seq]
        assert stamps == sorted(stamps)


def test_un_swing_se_rompe_una_sola_vez() -> None:
    n, df, _ = _load("bos_alcista")
    events = analyze_structure(df, n).events
    assert len({e.broken_swing_ts for e in events}) == len(events)


def test_fvg_zona_y_mitigacion_desde_fixture() -> None:
    _, df, expected = _load("fvg_alcista_mitigado")
    (fvg,) = find_fvgs(df)
    assert fvg.ts == datetime.fromisoformat(expected["fvgs"][0]["ts"])
    assert fvg.mitigated_at == datetime.fromisoformat(expected["fvgs"][0]["mitigated_at"])
