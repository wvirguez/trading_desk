"""Acceso a `agent_analyses`: pasos de análisis, solo inserción (D88)."""

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_analysis import AgentAnalysis, StepStatus
from app.schemas.enums import AnalysisStep, Timeframe


async def insert_step(
    session: AsyncSession,
    *,
    analysis_id: uuid.UUID,
    step: AnalysisStep,
    instrument_id: int,
    timeframe: Timeframe,
    input: dict[str, Any],
    output: dict[str, Any] | None = None,
    trace: dict[str, Any] | None = None,
    model: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: Decimal | None = None,
    latency_ms: int = 0,
    status: StepStatus = StepStatus.OK,
    error: str | None = None,
) -> AgentAnalysis:
    """Inserta un paso y lo devuelve con `id` y `created_at` cargados.

    Es el único método de escritura (la BD rechaza UPDATE y DELETE). Hace `flush` pero no
    `commit`: lo decide quien llama (D21). `input`, `output` y `trace` deben ser JSON puro.
    """
    row = AgentAnalysis(
        analysis_id=analysis_id,
        step=step.value,
        instrument_id=instrument_id,
        timeframe=timeframe.value,
        input=input,
        output=output,
        trace=trace,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        status=status.value,
        error=error,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def list_by_analysis(session: AsyncSession, analysis_id: uuid.UUID) -> list[AgentAnalysis]:
    """Pasos de un análisis en orden de inserción (`created_at`, desempate por `id`)."""
    stmt = (
        select(AgentAnalysis)
        .where(AgentAnalysis.analysis_id == analysis_id)
        .order_by(AgentAnalysis.created_at, AgentAnalysis.id)
    )
    return list((await session.execute(stmt)).scalars())
