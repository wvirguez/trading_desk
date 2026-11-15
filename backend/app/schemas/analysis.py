"""Esquemas de la API de análisis con agentes: petición, informe y eventos SSE."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    RootModel,
    field_validator,
    model_validator,
)

from app.schemas.agents import MarketStructureReport, QuantAlphaReport, RiskVerdict
from app.schemas.enums import AnalysisOutcome, AnalysisStep, Timeframe
from app.schemas.risk import GuardDecision
from app.schemas.signals import ProposedSignal, TradeSignalSchema

_CONFIG = ConfigDict(frozen=True, extra="forbid")


def _default_timeframes() -> list[Timeframe]:
    return [Timeframe.M15, Timeframe.H1, Timeframe.H4, Timeframe.D1]


class AnalyzeRequest(BaseModel):
    model_config = _CONFIG

    symbol: str
    timeframe: Timeframe = Timeframe.H1  # marco de entrada
    timeframes: list[Timeframe] = Field(default_factory=_default_timeframes)

    @field_validator("symbol")
    @classmethod
    def _symbol_no_vacio(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("symbol no puede estar vacío")
        return value

    @model_validator(mode="after")
    def _coherencia(self) -> Self:
        marcos = [t.value for t in self.timeframes]
        if len(set(self.timeframes)) != len(self.timeframes):
            raise ValueError(f"timeframes no puede repetir marcos temporales: {marcos}")
        if self.timeframe not in self.timeframes:
            raise ValueError(
                f"timeframe ({self.timeframe.value}) debe estar incluido en timeframes ({marcos})"
            )
        return self


class StepUsage(BaseModel):
    model_config = _CONFIG

    model: str | None = None
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: Decimal | None = None  # null sin precios configurados (D95)
    latency_ms: int = Field(default=0, ge=0)


class AgentReportSchema(BaseModel):
    model_config = _CONFIG

    analysis_id: UUID
    symbol: str
    timeframe: Timeframe
    outcome: AnalysisOutcome
    structure: MarketStructureReport | None = None
    quant: QuantAlphaReport | None = None
    proposal: ProposedSignal | None = None
    guards: GuardDecision | None = None
    risk_verdict: RiskVerdict | None = None
    signal: TradeSignalSchema | None = None
    usage: StepUsage  # suma de los pasos
    warnings: list[str] = Field(default_factory=list)


class _EventBase(BaseModel):
    model_config = _CONFIG

    analysis_id: UUID
    seq: int = Field(ge=0)  # creciente dentro de un análisis


class AnalysisStarted(_EventBase):
    event: Literal["analysis_started"] = "analysis_started"
    symbol: str
    timeframe: Timeframe
    timeframes: list[Timeframe]
    started_at: datetime


class StepStarted(_EventBase):
    event: Literal["step_started"] = "step_started"
    step: AnalysisStep


class StepCompleted(_EventBase):
    event: Literal["step_completed"] = "step_completed"
    step: AnalysisStep
    output: dict[str, JsonValue]
    usage: StepUsage


class StepFailed(_EventBase):
    event: Literal["step_failed"] = "step_failed"
    step: AnalysisStep
    error: str
    usage: StepUsage | None = None


class AnalysisCompleted(_EventBase):
    event: Literal["analysis_completed"] = "analysis_completed"
    report: AgentReportSchema


class AnalysisFailed(_EventBase):
    event: Literal["analysis_failed"] = "analysis_failed"
    error: str
    step: AnalysisStep | None = None


AnalysisEvent = Annotated[
    AnalysisStarted | StepStarted | StepCompleted | StepFailed | AnalysisCompleted | AnalysisFailed,
    Field(discriminator="event"),
]


class AnalysisEventEnvelope(RootModel[AnalysisEvent]):
    """Envoltorio nombrado de la unión discriminada, solo para publicar el tipo en OpenAPI (D108).

    El protocolo SSE no cambia: cada ``data:`` sigue siendo el JSON de UN evento (no del
    envoltorio); ``RootModel`` serializa exactamente como la unión.
    """
