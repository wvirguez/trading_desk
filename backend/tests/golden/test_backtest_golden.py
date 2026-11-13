"""Tests golden del backtester (4G.5): igualdad exacta sobre valores redondeados (D59).

Los datos (`data/*.csv`) y las métricas (`expected/*.json`) están versionados. Si un test
falla es porque cambió el algoritmo o los datos. Si el cambio es intencionado, regenera con
`cd backend && uv run python scripts/make_golden.py --update` y REVISA a mano las métricas
(diff de `tests/golden/expected/`) antes de aceptarlas.
"""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "make_golden.py"
_EXPECTED = Path(__file__).resolve().parent / "expected"
NAMES = ["mean_reverting", "trending", "random_walk"]

HINT = (
    "Resultado distinto del golden '{name}'. Si el cambio de algoritmo/datos es intencionado: "
    "`cd backend && uv run python scripts/make_golden.py --update` y revisa a mano el diff de "
    "tests/golden/expected/ (la revisión humana es obligatoria, principio 6)."
)


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("make_golden", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["make_golden"] = module
    spec.loader.exec_module(module)
    return module


golden = _load_script()


@pytest.mark.parametrize("name", NAMES)
def test_golden_coincide_con_lo_esperado(name: str) -> None:
    expected = json.loads((_EXPECTED / f"{name}.json").read_text())
    actual = golden.compute_expected(name)
    assert actual == expected, HINT.format(name=name)


@pytest.mark.parametrize("name", NAMES)
def test_golden_dos_ejecuciones_identicas(name: str) -> None:
    first = golden.compute_expected(name)
    second = golden.compute_expected(name)
    assert first == second
    assert first["config_hash"] == second["config_hash"]


def test_golden_metricas_razonables() -> None:
    exp = {n: json.loads((_EXPECTED / f"{n}.json").read_text()) for n in NAMES}
    assert exp["mean_reverting"]["total_return"] > 0
    assert exp["trending"]["total_return"] < exp["mean_reverting"]["total_return"]
    for e in exp.values():
        assert e["n_bars"] == 1500
        assert e["max_drawdown"] <= 0
        assert 0 <= e["win_rate"] <= 1
