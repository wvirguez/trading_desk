"""Contrato del endpoint `GET /api/v1/health`."""

from typing import Literal

from pydantic import BaseModel, Field


class HealthSchema(BaseModel):
    status: Literal["ok", "degraded"] = Field(
        description="`ok` solo si la base de datos responde y TimescaleDB está instalado."
    )
    version: str = Field(description="Versión del backend.")
    database: Literal["ok", "error"] = Field(description="Resultado de `SELECT 1`.")
    timescaledb: str | None = Field(
        description="Versión de la extensión timescaledb, o `null` si no está instalada "
        "o la base de datos no responde."
    )
