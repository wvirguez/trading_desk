"""Modelo ORM de `agent_analyses`: un paso de un análisis multiagente (solo inserción, D88)."""

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.checks import enum_check
from app.schemas.enums import AnalysisStep, Timeframe


class StepStatus(StrEnum):
    """Resultado de un paso persistido (solo existe en la capa de persistencia)."""

    OK = "OK"
    ERROR = "ERROR"


class AgentAnalysis(Base):
    __tablename__ = "agent_analyses"
    __table_args__ = (
        CheckConstraint(enum_check("step", AnalysisStep), name="ck_agent_analyses_step"),
        CheckConstraint(enum_check("timeframe", Timeframe), name="ck_agent_analyses_timeframe"),
        CheckConstraint(enum_check("status", StepStatus), name="ck_agent_analyses_status"),
        UniqueConstraint("analysis_id", "step", name="uq_agent_analyses_analysis_id_step"),
        Index("ix_agent_analyses_analysis_id", "analysis_id"),
        Index(
            "ix_agent_analyses_instrument_id_created_at", "instrument_id", text("created_at DESC")
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    step: Mapped[str] = mapped_column(Text)
    instrument_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("instruments.id"))
    timeframe: Mapped[str] = mapped_column(Text)
    input: Mapped[dict[str, Any]] = mapped_column(JSONB)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    trace: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
