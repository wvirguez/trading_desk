"""Tests de `scripts/export_openapi.py` (D18)."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "export_openapi.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("export_openapi", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_export_es_determinista(tmp_path: Path) -> None:
    module = _load()
    first, second = tmp_path / "a.json", tmp_path / "b.json"

    module.export(first)
    module.export(second)

    assert first.read_bytes() == second.read_bytes()


def test_export_formato(tmp_path: Path) -> None:
    module = _load()
    target = tmp_path / "openapi.json"

    module.export(target)

    text = target.read_text(encoding="utf-8")
    assert text.endswith("}\n")
    spec = json.loads(text)
    assert "/api/v1/market/ohlcv" in spec["paths"]
    assert json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=False) + "\n" == text
