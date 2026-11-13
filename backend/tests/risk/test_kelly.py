"""Kelly fraccional y riesgo de ruina (D61)."""

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.risk.kelly import kelly_fraction, risk_of_ruin

probs = st.floats(0.0, 1.0)
ratios = st.floats(0.05, 20.0)
fracs = st.floats(0.01, 1.0)
caps = st.floats(0.001, 1.0)
risk_fracs = st.floats(0.001, 1.0)


def test_valores_conocidos() -> None:
    r = kelly_fraction(0.6, 1.0, 1.0, 1.0)
    assert r.full_kelly == pytest.approx(0.2)
    assert r.fraction == pytest.approx(0.2)
    assert not r.capped
    r0 = kelly_fraction(0.5, 1.0, 0.25, 0.01)
    assert r0.full_kelly == 0.0
    assert r0.fraction == 0.0
    assert not r0.capped


def test_tope() -> None:
    r = kelly_fraction(0.6, 1.0, 0.25, 0.01)  # 0.25*0.2 = 0.05 > 0.01
    assert r.fraction == 0.01
    assert r.capped


def test_ruina_valores() -> None:
    assert risk_of_ruin(0.5, 1.0, 0.01) == 1.0
    # A = 0.2 -> (0.8/1.2)^100 muy pequeño
    assert risk_of_ruin(0.6, 1.0, 0.01) == pytest.approx((0.8 / 1.2) ** 100)
    assert risk_of_ruin(0.6, 1.0, 1.0) == pytest.approx(0.8 / 1.2)
    assert risk_of_ruin(1.0, 1.0, 0.5) == 0.0


@pytest.mark.parametrize(
    "args", [(1.2, 1.0), (-0.1, 1.0), (0.5, 0.0), (0.5, -1.0), (0.5, math.inf)]
)
def test_valores_invalidos(args: tuple[float, float]) -> None:
    with pytest.raises(ValueError, match="recibido"):
        kelly_fraction(*args, 0.25, 0.01)
    with pytest.raises(ValueError, match="recibido"):
        risk_of_ruin(*args, 0.01)


def test_parametros_invalidos() -> None:
    for fraction in (0.0, 1.5):
        with pytest.raises(ValueError, match="recibido"):
            kelly_fraction(0.6, 1.0, fraction, 0.01)
    with pytest.raises(ValueError, match="recibido"):
        kelly_fraction(0.6, 1.0, 0.25, 0.0)
    for r in (0.0, 1.5, -0.1):
        with pytest.raises(ValueError, match="recibido"):
            risk_of_ruin(0.6, 1.0, r)


@settings(derandomize=True, max_examples=200)
@given(probs, ratios, fracs, caps)
def test_fraccion_acotada(p: float, b: float, fraction: float, cap: float) -> None:
    r = kelly_fraction(p, b, fraction, cap)
    assert 0.0 <= r.fraction <= cap
    assert r.full_kelly >= 0.0


@settings(derandomize=True, max_examples=200)
@given(probs, ratios, risk_fracs)
def test_ruina_en_rango(p: float, b: float, r: float) -> None:
    assert 0.0 <= risk_of_ruin(p, b, r) <= 1.0


@settings(derandomize=True, max_examples=200)
@given(probs, ratios, risk_fracs, risk_fracs)
def test_ruina_no_decrece_con_riesgo(p: float, b: float, r1: float, r2: float) -> None:
    lo, hi = sorted((r1, r2))
    assert risk_of_ruin(p, b, lo) <= risk_of_ruin(p, b, hi)


@settings(derandomize=True, max_examples=200)
@given(probs, probs, ratios, risk_fracs)
def test_ruina_no_crece_con_p(p1: float, p2: float, b: float, r: float) -> None:
    lo, hi = sorted((p1, p2))
    assert risk_of_ruin(hi, b, r) <= risk_of_ruin(lo, b, r)
