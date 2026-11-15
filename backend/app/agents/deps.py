"""Dependencias de ejecución de los agentes: solo datos ya cargados, sin acceso a la BD."""

from collections.abc import Mapping
from dataclasses import dataclass, field

import polars as pl

from app.core.config import Settings
from app.schemas.enums import Timeframe
from app.schemas.instrument import InstrumentSchema
from app.schemas.risk import KellyResult, PortfolioState


@dataclass(frozen=True)
class AgentDeps:
    """Contexto numérico que reciben las herramientas de los agentes.

    `candles` contiene un DataFrame de `app.quant.data.candles_to_frame` por marco temporal.
    """

    instrument: InstrumentSchema
    candles: Mapping[Timeframe, pl.DataFrame]
    settings: Settings
    portfolio: PortfolioState
    # Estado por ejecución del QuantAlphaAgent: llamadas a la herramienta `kelly` como
    # `(p, b, resultado)`. Cada `AgentDeps` tiene su propia lista (sin estado global); el
    # validador de salida la lee para comprobar que `kelly` salió de la herramienta.
    kelly_calls: list[tuple[float, float, KellyResult]] = field(
        default_factory=list, compare=False, repr=False
    )
