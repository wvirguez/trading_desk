"""Reglas de arquitectura (D66): el núcleo cuantitativo y de riesgo es código puro.

`app/quant/` y `app/risk/` no importan FastAPI, SQLAlchemy, httpx, pydantic_ai ni anthropic;
el I/O vive en `services/` y `api/`. Además, `pandas` solo se usa en `market_data/yahoo.py` y
`scipy` no se importa directamente en el código propio.
"""

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent / "app"
PURE_PACKAGES = ("quant", "risk")
FORBIDDEN_IN_PURE = {"fastapi", "sqlalchemy", "httpx", "starlette", "asyncpg"}
FORBIDDEN_AI = {"pydantic_ai", "anthropic"}  # D97: los agentes viven en `agents/`


def _imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def _py_files(package: str) -> list[Path]:
    return sorted((APP / package).rglob("*.py"))


def test_pure_packages_have_files() -> None:
    # Evita que el test pase en vacío si cambia la estructura.
    for package in PURE_PACKAGES:
        assert _py_files(package), f"app/{package} no tiene módulos"


@pytest.mark.parametrize("package", PURE_PACKAGES)
def test_pure_packages_do_not_import_web_or_db(package: str) -> None:
    offenders = {
        str(path.relative_to(APP)): sorted(_imported_roots(path) & FORBIDDEN_IN_PURE)
        for path in _py_files(package)
        if _imported_roots(path) & FORBIDDEN_IN_PURE
    }
    assert not offenders, f"Imports prohibidos en código puro: {offenders}"


@pytest.mark.parametrize("package", PURE_PACKAGES)
def test_pure_packages_do_not_import_ai_sdks(package: str) -> None:
    offenders = {
        str(path.relative_to(APP)): sorted(_imported_roots(path) & FORBIDDEN_AI)
        for path in _py_files(package)
        if _imported_roots(path) & FORBIDDEN_AI
    }
    assert not offenders, f"pydantic_ai/anthropic en código puro: {offenders}"


def test_pandas_and_scipy_stay_out_of_own_code() -> None:
    allowed_pandas = APP / "market_data" / "yahoo.py"
    offenders: dict[str, list[str]] = {}
    for path in sorted(APP.rglob("*.py")):
        banned = {"scipy"} | (set() if path == allowed_pandas else {"pandas"})
        found = sorted(_imported_roots(path) & banned)
        if found:
            offenders[str(path.relative_to(APP))] = found
    assert not offenders, f"pandas/scipy fuera de lo permitido: {offenders}"
