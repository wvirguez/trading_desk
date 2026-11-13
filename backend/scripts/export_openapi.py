"""Escribe `backend/openapi.json` de forma determinista (D18).

Uso: `uv run python scripts/export_openapi.py`
"""

import json
from pathlib import Path

from app.main import app

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "openapi.json"


def export(path: Path = DEFAULT_PATH) -> None:
    text = json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    export()
    print(f"OpenAPI escrito en {DEFAULT_PATH}")
