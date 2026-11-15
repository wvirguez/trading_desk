"""Esquemas de salida de los agentes. Un LLM que añade campos falla la validación."""

from datetime import datetime
from decimal import Decimal
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.enums import (
    AuditDecision,
    Bias,
    Playbook,
    RegimeLabel,
    StructureEventType,
    Timeframe,
)
from app.schemas.quant import RegimeStats
from app.schemas.risk import GuardDecision, KellyResult

MAX_REASONING_CHARS = 1500

_AGENT_CONFIG = ConfigDict(frozen=True, extra="forbid")


class TimeframeStructure(BaseModel):
    model_config = _AGENT_CONFIG

    timeframe: Timeframe
    bias: Bias
    last_event: StructureEventType | None = None
    key_levels: list[Decimal]  # deben existir en la salida de las herramientas
    open_fvg_ts: list[datetime]  # FVG no mitigados que cita
    comment: str = Field(max_length=MAX_REASONING_CHARS)


class MarketStructureReport(BaseModel):
    """Lectura multi-timeframe: exige al menos 2 marcos distintos entre sí."""

    model_config = _AGENT_CONFIG

    symbol: str
    entry_timeframe: Timeframe
    timeframes: list[TimeframeStructure] = Field(min_length=2)
    htf_alignment: Bias
    zone_ts: datetime | None = None  # FVG elegido como zona de entrada
    invalidation_level: Decimal | None = None
    reasoning: str = Field(max_length=MAX_REASONING_CHARS)

    @model_validator(mode="after")
    def _marcos_unicos(self) -> Self:
        marcos = [t.timeframe for t in self.timeframes]
        if len(set(marcos)) != len(marcos):
            raise ValueError(
                f"timeframes no puede repetir marcos temporales: {[m.value for m in marcos]}"
            )
        return self


class QuantAlphaReport(BaseModel):
    model_config = _AGENT_CONFIG

    symbol: str
    timeframe: Timeframe
    regime: RegimeLabel  # debe coincidir con el clasificador
    stats: RegimeStats  # copia de la herramienta
    playbook: Playbook
    kelly: KellyResult | None = None  # solo informativo (D86)
    reasoning: str = Field(max_length=MAX_REASONING_CHARS)


class RiskVerdict(BaseModel):
    model_config = _AGENT_CONFIG

    decision: AuditDecision
    deterministic: GuardDecision  # copiada por el orquestador, no escrita por el LLM
    concerns: list[str]
    rationale: str


class AuditorOutput(BaseModel):
    """Salida reducida del `RiskAuditorAgent`: el LLM no escribe `deterministic` (D94)."""

    model_config = _AGENT_CONFIG

    decision: AuditDecision
    concerns: list[str]
    rationale: str = Field(max_length=MAX_REASONING_CHARS)
