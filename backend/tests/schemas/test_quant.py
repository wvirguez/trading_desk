import json
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.enums import Direction, RegimeLabel, SwingKind, Timeframe
from app.schemas.quant import (
    BacktestConfig,
    BacktestMetricsSchema,
    EquityPoint,
    FairValueGap,
    MarketStructureResult,
    RegimeReport,
    RegimeStats,
    RegimeThresholds,
    SwingPoint,
)

T0 = datetime(2024, 1, 1, tzinfo=UTC)


def _config(**kw: Any) -> BacktestConfig:
    return BacktestConfig(symbol="EUR/USD", timeframe=Timeframe.H1, **kw)


def test_backtest_config_valores_por_defecto() -> None:
    c = _config()
    assert c.initial_capital == Decimal(10000)
    assert (c.zscore_window, c.entry_z, c.exit_z, c.allow_short) == (50, 2.0, 0.0, True)
    assert c.start is None
    assert c.end is None


@pytest.mark.parametrize(
    ("kw", "msg"),
    [
        ({"exit_z": 2.0}, "exit_z"),
        ({"exit_z": 3.0}, "exit_z"),
        ({"entry_z": 0.0}, "entry_z"),
        ({"exit_z": -0.1}, "exit_z"),
        ({"zscore_window": 9}, "zscore_window"),
        ({"zscore_window": 501}, "zscore_window"),
        ({"initial_capital": Decimal(0)}, "initial_capital"),
        ({"initial_capital": Decimal(-5)}, "initial_capital"),
        ({"start": T0, "end": T0}, "start"),
        ({"start": T0 + timedelta(days=1), "end": T0}, "start"),
        ({"start": datetime(2024, 1, 1)}, "zona horaria"),
    ],
)
def test_backtest_config_rechaza_invalidos(kw: dict[str, Any], msg: str) -> None:
    with pytest.raises(ValidationError, match=msg):
        _config(**kw)


@pytest.mark.parametrize("symbol", ["", "   "])
def test_backtest_config_rechaza_symbol_vacio(symbol: str) -> None:
    with pytest.raises(ValidationError, match="symbol"):
        BacktestConfig(symbol=symbol, timeframe=Timeframe.H1)


@pytest.mark.parametrize("window", [10, 500])
def test_backtest_config_limites_de_ventana_validos(window: int) -> None:
    assert _config(zscore_window=window).zscore_window == window


def test_backtest_config_normaliza_fechas_a_utc() -> None:
    tz = timezone(timedelta(hours=2))
    c = _config(start=datetime(2024, 1, 1, 2, tzinfo=tz), end=datetime(2024, 1, 2, 2, tzinfo=tz))
    assert c.start == T0
    assert c.start is not None
    assert c.start.utcoffset() == timedelta(0)


def test_decimal_viaja_como_cadena_en_json() -> None:
    c = _config(initial_capital=Decimal("12345.67"))
    metrics = BacktestMetricsSchema(
        strategy_id=uuid4(),
        config=c,
        n_bars=100,
        n_trades=2,
        total_return=0.1,
        sharpe=1.0,
        max_drawdown=-0.05,
        win_rate=0.5,
        expectancy=0.01,
        final_equity=Decimal("13000.50"),
        equity_curve=[EquityPoint(ts=T0, equity=Decimal("12345.67"))],
        warnings=[],
    )
    data = json.loads(metrics.model_dump_json())
    assert data["final_equity"] == "13000.50"
    assert data["config"]["initial_capital"] == "12345.67"
    assert data["equity_curve"][0]["equity"] == "12345.67"
    assert BacktestMetricsSchema.model_validate(data) == metrics


def test_swing_y_fvg_decimal_como_cadena() -> None:
    sp = SwingPoint(ts=T0, kind=SwingKind.HIGH, price=Decimal("1.10500"), confirmed_at=T0)
    assert json.loads(sp.model_dump_json())["price"] == "1.10500"
    fvg = FairValueGap(ts=T0, direction=Direction.LONG, low=Decimal("1.1"), high=Decimal("1.2"))
    assert fvg.mitigated_at is None
    assert json.loads(fvg.model_dump_json())["high"] == "1.2"


def test_regime_thresholds_por_defecto() -> None:
    t = RegimeThresholds()
    assert (t.hurst_mean_reverting, t.hurst_trending, t.adf_alpha) == (0.45, 0.55, 0.05)
    assert (t.vol_ratio_high, t.min_obs) == (1.5, 100)


def test_inmutabilidad() -> None:
    c = _config()
    with pytest.raises(ValidationError):
        c.entry_z = 3.0  # type: ignore[misc]
    stats = RegimeStats(hurst=0.4, adf_pvalue=0.01, zscore=1.0, volatility_ratio=1.0, n_obs=200)
    report = RegimeReport(
        label=RegimeLabel.MEAN_REVERTING, stats=stats, thresholds=RegimeThresholds()
    )
    with pytest.raises(ValidationError):
        report.label = RegimeLabel.TRENDING  # type: ignore[misc]
    result = MarketStructureResult(swings=[], events=[], fvgs=[])
    with pytest.raises(ValidationError):
        result.swings = []  # type: ignore[misc]
