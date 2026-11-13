"""Genera los datasets sintéticos golden del backtester (4G.4) y sus métricas esperadas.

Uso (desde `backend/`):

    uv run python scripts/make_golden.py            # regenera SOLO los CSV (si faltan o cambian)
    uv run python scripts/make_golden.py --update   # además regenera tests/golden/expected/*.json

Los CSV se versionan: son la fuente de verdad de los datos (los precios van como texto con
5 decimales para no depender del formato `float`). Las series usan
`numpy.random.default_rng(seed)` (PCG64, estable entre versiones). Regenerar los JSON exige
revisión humana de las métricas (misión, principio 6): no se fuerzan para que "cuadren".
"""

import argparse
import csv
import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import numpy as np
from numpy.typing import NDArray

from app.quant.backtest import config_hash, periods_per_year, run_backtest, to_metrics_schema
from app.quant.data import candles_to_frame
from app.schemas.candle import CandleSchema
from app.schemas.enums import SessionType, Timeframe
from app.schemas.quant import BacktestConfig

ROOT = Path(__file__).resolve().parent.parent / "tests" / "golden"
DATA_DIR = ROOT / "data"
EXPECTED_DIR = ROOT / "expected"
N_BARS = 1500
START = datetime(2024, 1, 1, tzinfo=UTC)
SYMBOL = "EUR/USD"
SESSION = SessionType.FX_24_5
GOLDEN_CONFIG = BacktestConfig(symbol=SYMBOL, timeframe=Timeframe.H1)  # valores por defecto
NIL_UUID = UUID(int=0)
DATASETS: dict[str, int] = {"mean_reverting": 101, "trending": 202, "random_walk": 303}


def _closes(name: str, seed: int) -> NDArray[np.float64]:
    rng = np.random.default_rng(seed)
    eps = rng.normal(0.0, 0.001, N_BARS)
    if name == "mean_reverting":  # Ornstein-Uhlenbeck discreto alrededor de 1.10
        x = np.empty(N_BARS)
        x[0] = 1.10
        for t in range(1, N_BARS):
            x[t] = 1.10 + 0.9 * (x[t - 1] - 1.10) + eps[t]
        return x
    if name == "trending":  # incrementos con deriva y persistencia
        u = np.zeros(N_BARS)
        for t in range(1, N_BARS):
            u[t] = 0.7 * u[t - 1] + eps[t]
        steps = 0.0002 + u
        steps[0] = 0.0
        return np.asarray(1.10 + np.cumsum(steps), dtype=np.float64)
    steps = eps.copy()  # random walk
    steps[0] = 0.0
    return np.asarray(1.10 + np.cumsum(steps), dtype=np.float64)


def _rows(name: str, seed: int) -> list[list[str]]:
    rng = np.random.default_rng(seed + 1)
    closes = np.round(_closes(name, seed), 5)
    wick = np.abs(rng.normal(0.0, 0.0004, (N_BARS, 2)))
    vol = rng.integers(100, 10000, N_BARS)
    rows: list[list[str]] = []
    prev = float(closes[0])
    for i in range(N_BARS):
        o, c = prev, float(closes[i])
        h = round(max(o, c) + float(wick[i, 0]), 5)
        low = round(min(o, c) - float(wick[i, 1]), 5)
        ts = (START + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows.append([ts, f"{o:.5f}", f"{h:.5f}", f"{low:.5f}", f"{c:.5f}", str(int(vol[i]))])
        prev = c
    return rows


def write_csv(name: str, seed: int) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with (DATA_DIR / f"{name}.csv").open("w", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(["ts", "open", "high", "low", "close", "volume"])
        writer.writerows(_rows(name, seed))


def load_candles(name: str) -> list[CandleSchema]:
    with (DATA_DIR / f"{name}.csv").open(newline="") as fh:
        return [
            CandleSchema(
                symbol=SYMBOL,
                timeframe=Timeframe.H1,
                ts=datetime.fromisoformat(r["ts"]),
                open=Decimal(r["open"]),
                high=Decimal(r["high"]),
                low=Decimal(r["low"]),
                close=Decimal(r["close"]),
                volume=Decimal(r["volume"]),
            )
            for r in csv.DictReader(fh)
        ]


def compute_expected(name: str) -> dict[str, object]:
    """Ejecuta el backtest golden y devuelve el resumen comparable (valores redondeados)."""
    candles = load_candles(name)
    df = candles_to_frame(candles)
    result = run_backtest(df, GOLDEN_CONFIG, periods_per_year(Timeframe.H1, SESSION))
    metrics = to_metrics_schema(result, GOLDEN_CONFIG, NIL_UUID, [])
    curve = [f"{p.ts.isoformat()}={p.equity}" for p in metrics.equity_curve]
    return {
        "config_hash": config_hash(GOLDEN_CONFIG, candles[0].ts, candles[-1].ts),
        "n_bars": metrics.n_bars,
        "n_trades": metrics.n_trades,
        "total_return": metrics.total_return,
        "sharpe": metrics.sharpe,
        "max_drawdown": metrics.max_drawdown,
        "win_rate": metrics.win_rate,
        "expectancy": metrics.expectancy,
        "final_equity": str(metrics.final_equity),
        "equity_curve_sha256": hashlib.sha256("\n".join(curve).encode()).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--update", action="store_true", help="regenera expected/*.json")
    args = parser.parse_args()
    for name, seed in DATASETS.items():
        write_csv(name, seed)
        print(f"CSV escrito: {DATA_DIR / (name + '.csv')}")
    if args.update:
        EXPECTED_DIR.mkdir(parents=True, exist_ok=True)
        for name in DATASETS:
            expected = compute_expected(name)
            path = EXPECTED_DIR / f"{name}.json"
            path.write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n")
            print(f"{name}: {json.dumps(expected)}")


if __name__ == "__main__":
    main()
