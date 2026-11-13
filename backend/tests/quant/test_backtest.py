"""Tests del backtester vectorizado (4G). Las series pequeñas están calculadas a mano."""

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import numpy as np
import polars as pl
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.quant.backtest import (
    config_hash,
    periods_per_year,
    run_backtest,
    to_metrics_schema,
)
from app.quant.regime_stats import zscore
from app.schemas.enums import SessionType, Timeframe
from app.schemas.quant import BacktestConfig

T0 = datetime(2024, 1, 1, tzinfo=UTC)
P = 252 * 24


def frame(closes: list[float] | np.ndarray) -> pl.DataFrame:
    n = len(closes)
    return pl.DataFrame(
        {
            "ts": [T0 + timedelta(hours=i) for i in range(n)],
            "close": [float(c) for c in closes],
        },
        schema={"ts": pl.Datetime("us", "UTC"), "close": pl.Float64},
    )


def cfg(**kw: object) -> BacktestConfig:
    base: dict[str, object] = {"symbol": "EUR/USD", "timeframe": Timeframe.H1, "zscore_window": 10}
    base.update(kw)
    return BacktestConfig.model_validate(base)


# Base: 10 velas alternando 100/101 (la ultima, idx 9, vale 101).
BASE = [100.0, 101.0] * 5


# ---------------------------------------------------------------- periods_per_year
def test_periods_per_year() -> None:
    assert periods_per_year(Timeframe.D1, SessionType.CRYPTO_24_7) == 365
    assert periods_per_year(Timeframe.D1, SessionType.FX_24_5) == 252
    assert periods_per_year(Timeframe.D1, SessionType.INDEX_CFD) == 252
    assert periods_per_year(Timeframe.H1, SessionType.FX_24_5) == 252 * 24
    assert periods_per_year(Timeframe.H1, SessionType.CRYPTO_24_7) == 365 * 24
    assert periods_per_year(Timeframe.H4, SessionType.FX_24_5) == 252 * 6


# ---------------------------------------------------------------- casos a mano
def test_sin_senales_capital_constante() -> None:
    res = run_backtest(frame([100.0] * 40), cfg(), P)  # z nulo siempre (serie constante)
    assert res.n_trades == 0
    assert np.all(res.equity == 10000.0)
    assert res.total_return == 0.0
    assert res.sharpe == 0.0  # std = 0
    assert res.win_rate == 0.0
    assert res.expectancy == 0.0
    assert res.max_drawdown == 0.0


def test_zscore_de_la_serie_manual() -> None:
    # idx 10 = 90: ventana idx1..10 -> media 99.5, std 3.375 -> z = -9.5/3.375 = -2.81
    z = zscore(pl.Series([*BASE, 90.0]), 10)
    assert z[10] == pytest.approx(-9.5 / math.sqrt(102.5 / 9))
    assert z[10] <= -2.0
    assert z[9] is not None and abs(z[9]) < 2.0


def test_operacion_larga_resultado_conocido() -> None:
    # idx10 = 90 -> z = -2.81 <= -2: entrada larga decidida en el cierre de idx10.
    # idx11 = 95 -> z = -1.08 (mantiene); idx12 = 100 -> z = +0.3 >= 0: salida decidida.
    # Posicion aplicada (shift 1): idx11 y idx12 = +1; idx13 = 0.
    # Retornos: 95/90 y 100/95 -> producto telescopico = 100/90 -> +11.11 %.
    closes = [*BASE, 90.0, 95.0, 100.0, 101.0]
    res = run_backtest(frame(closes), cfg(), P)
    assert list(res.position) == [0.0] * 11 + [1.0, 1.0, 0.0]
    assert res.n_trades == 1
    assert res.trade_returns[0] == pytest.approx(100.0 / 90.0 - 1.0)
    assert res.equity[10] == 10000.0
    assert res.equity[11] == pytest.approx(10000.0 * 95.0 / 90.0)
    assert res.equity[12] == pytest.approx(10000.0 * 100.0 / 90.0)
    assert res.equity[13] == pytest.approx(res.equity[12])  # ya plano: el 100->101 no cuenta
    assert res.total_return == pytest.approx(1.0 / 9.0)
    assert res.win_rate == 1.0
    assert res.expectancy == pytest.approx(1.0 / 9.0)
    assert res.max_drawdown == 0.0
    assert res.sharpe > 0.0


def test_shift1_el_salto_de_la_senal_no_se_atribuye() -> None:
    # La caida 101 -> 90 en idx10 es la barra de la senal: la posicion aun es 0 ahi.
    # El salto posterior 90 -> 99 (idx11) si lo gana la posicion larga.
    res = run_backtest(frame([*BASE, 90.0, 99.0]), cfg(), P)
    assert res.position[10] == 0.0
    assert res.position[11] == 1.0
    assert res.equity[10] == 10000.0
    assert res.equity[11] == pytest.approx(10000.0 * 99.0 / 90.0)


def test_entrada_y_salida_en_velas_consecutivas() -> None:
    # idx10 = 90 entra; idx11 = 101 -> z > 0 sale. Solo idx11 lleva posicion: 101/90 - 1.
    res = run_backtest(frame([*BASE, 90.0, 101.0, 101.0]), cfg(), P)
    assert list(res.position[10:]) == [0.0, 1.0, 0.0]
    assert res.n_trades == 1
    assert res.trade_returns[0] == pytest.approx(101.0 / 90.0 - 1.0)


def test_corto_gana_si_el_precio_cae() -> None:
    # Base alternando 100/99 (idx9 = 99); idx10 = 110 -> z alto: corto. idx11 = 100.
    base = [100.0, 99.0] * 5
    closes = [*base, 110.0, 100.0, 99.0, 99.0]
    res = run_backtest(frame(closes), cfg(), P)
    assert res.position[10] == 0.0
    assert res.position[11] == -1.0
    # Primera barra del corto: el activo cae 110 -> 100, el corto gana 1 - 100/110.
    assert res.equity[11] == pytest.approx(10000.0 * (1.0 + (1.0 - 100.0 / 110.0)))
    assert res.n_trades == 1
    assert res.trade_returns[0] > 0.0


def test_allow_short_false_no_abre_cortos() -> None:
    base = [100.0, 99.0] * 5
    closes = [*base, 110.0, 100.0, 99.0, 99.0]
    res = run_backtest(frame(closes), cfg(allow_short=False), P)
    assert np.all(res.position >= 0.0)
    assert res.n_trades == 0
    assert np.all(res.equity == 10000.0)


def test_cambio_directo_de_corto_a_largo() -> None:
    # idx10 = 110 abre corto; idx11 = 80 -> z muy negativo: sale del corto y entra largo
    # en la misma vela. Posicion aplicada: idx11 = -1, idx12 = +1 -> dos operaciones.
    base = [100.0, 99.0] * 5
    closes = [*base, 110.0, 80.0, 85.0, 85.0]
    res = run_backtest(frame(closes), cfg(), P)
    assert list(res.position[10:13]) == [0.0, -1.0, 1.0]
    assert res.n_trades >= 2
    assert res.trade_returns[0] == pytest.approx(1.0 - 80.0 / 110.0)  # corto: gana 27.27 %


def test_nulls_iniciales_sin_posicion() -> None:
    res = run_backtest(frame([*BASE, 90.0, 95.0]), cfg(), P)
    assert np.all(res.position[:11] == 0.0)  # z nulo hasta idx8 y sin senal despues


def test_max_drawdown_negativo_con_perdida() -> None:
    # Largo en 90 que luego cae a 80: la curva baja desde su pico (el capital inicial).
    res = run_backtest(frame([*BASE, 90.0, 80.0, 80.0]), cfg(), P)
    assert res.max_drawdown == pytest.approx(80.0 / 90.0 - 1.0)
    assert res.max_drawdown <= 0.0
    assert res.total_return < 0.0


def test_n_bars_insuficientes() -> None:
    with pytest.raises(ValueError):
        run_backtest(frame([100.0]), cfg(), P)


# ---------------------------------------------------------------- sin look-ahead
def test_truncar_no_cambia_el_equity_calculado() -> None:
    rng = np.random.default_rng(7)
    closes = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, 400)))
    full = run_backtest(frame(closes), cfg(zscore_window=20, entry_z=1.0), P)
    for k in (60, 150, 399):
        part = run_backtest(frame(closes[:k]), cfg(zscore_window=20, entry_z=1.0), P)
        assert np.array_equal(part.equity, full.equity[:k])
    assert full.n_trades > 0


# ---------------------------------------------------------------- propiedades
@settings(derandomize=True, max_examples=100, deadline=None)
@given(
    st.lists(st.floats(min_value=-0.5, max_value=0.5), min_size=30, max_size=200),
    st.booleans(),
)
def test_propiedades_equity_y_win_rate(log_rets: list[float], allow_short: bool) -> None:
    closes = 100.0 * np.exp(np.cumsum(log_rets))  # retornos simples > -100 %
    res = run_backtest(frame(closes), cfg(entry_z=1.0, allow_short=allow_short), P)
    assert np.all(res.equity >= 0.0)
    assert 0.0 <= res.win_rate <= 1.0
    assert res.max_drawdown <= 0.0
    assert np.all(np.isin(res.position, (-1.0, 0.0, 1.0)))
    if not allow_short:
        assert np.all(res.position >= 0.0)


# ---------------------------------------------------------------- esquema y hash
def test_to_metrics_schema_redondeo_y_decimal() -> None:
    config = cfg()
    res = run_backtest(frame([*BASE, 90.0, 95.0, 100.0, 101.0]), config, P)
    out = to_metrics_schema(res, config, uuid4(), ["aviso"])
    assert out.n_bars == 14
    assert out.n_trades == 1
    assert out.total_return == round(1.0 / 9.0, 10)
    assert out.final_equity == Decimal("11111.1111111111")
    assert len(out.equity_curve) == 14
    assert out.equity_curve[0].equity == Decimal("10000.0")
    assert out.equity_curve[0].ts == T0
    assert out.warnings == ["aviso"]


def test_config_hash_estable_y_sensible() -> None:
    a, b = T0, T0 + timedelta(days=30)
    base = cfg()
    h = config_hash(base, a, b)
    assert h == config_hash(cfg(), a, b)
    assert len(h) == 64
    variantes = [
        cfg(symbol="GBP/USD"),
        cfg(timeframe=Timeframe.H4),
        cfg(start=T0),
        cfg(end=b),
        cfg(initial_capital=Decimal(5000)),
        cfg(zscore_window=11),
        cfg(entry_z=2.5),
        cfg(exit_z=0.5),
        cfg(allow_short=False),
    ]
    hashes = {config_hash(v, a, b) for v in variantes}
    assert h not in hashes
    assert len(hashes) == len(variantes)
    assert config_hash(base, a, b + timedelta(hours=1)) != h
    assert config_hash(base, a - timedelta(hours=1), b) != h


def test_config_hash_capital_equivalente() -> None:
    a, b = T0, T0 + timedelta(days=1)
    assert config_hash(cfg(initial_capital=Decimal("10000")), a, b) == config_hash(
        cfg(initial_capital=Decimal("10000.00")), a, b
    )
