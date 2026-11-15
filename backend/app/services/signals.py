"""Construcción y persistencia de `TradeSignalSchema` (D94, D96).

El estado final sale solo de `final_status` (guardas Y auditor). El tamaño es el de las guardas
(`position_size`); nada de aquí lo calcula el LLM.
"""

import uuid
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.risk_auditor import auditor_rejection_rationale, final_status
from app.repositories import trade_signals as signals_repo
from app.schemas.agents import MarketStructureReport, QuantAlphaReport, RiskVerdict
from app.schemas.enums import AuditDecision, SignalStatus
from app.schemas.instrument import InstrumentSchema
from app.schemas.risk import GuardDecision
from app.schemas.signals import (
    MAX_MODEL_TEXT_CHARS,
    UNVERIFIED_LABEL,
    ProposedSignal,
    TradeSignalSchema,
    model_text,
)

_RR_QUANTUM = Decimal("0.0001")  # `trade_signals.rr` es NUMERIC(10,4)


def _num(value: Decimal) -> str:
    return format(value, "f")


def _facts(proposal: ProposedSignal, guard: GuardDecision) -> str:
    """Cifras del rationale: todas salen del código (propuesta y guardas), nunca del LLM."""
    rr = (guard.rr if guard.rr is not None else proposal.rr).quantize(
        _RR_QUANTUM, rounding=ROUND_DOWN
    )
    return (
        f"{proposal.direction.value} {proposal.symbol} {proposal.timeframe.value}: entrada "
        f"{_num(proposal.entry)}, SL {_num(proposal.stop_loss)}, TP {_num(proposal.take_profit)}, "
        f"R:R {_num(rr)}."
    )


def _rationale(
    status: SignalStatus,
    proposal: ProposedSignal,
    guard: GuardDecision,
    verdict: RiskVerdict | None,
    structure: MarketStructureReport,
    quant: QuantAlphaReport,
) -> str:
    """Rationale con datos del código primero y la prosa del LLM etiquetada y acotada (D112)."""
    facts = _facts(proposal, guard)
    if not guard.approved:
        return f"Veto determinista: {'; '.join(guard.messages)}. {facts} {proposal.source}"
    if verdict is not None and verdict.decision is AuditDecision.VETO:
        return f"{facts} {auditor_rejection_rationale(verdict)}"
    if verdict is None or status is not SignalStatus.APPROVED:
        raise ValueError("Una señal aprobada exige guardas y auditor en APPROVE")
    return (
        f"{facts} {proposal.source}. Guardas deterministas: aprobadas. Sesgo HTF "
        f"{structure.htf_alignment.value}; régimen {quant.regime.value}; playbook "
        f"{quant.playbook.value}; auditor: {verdict.decision.value}. "
        f"Texto del modelo ({UNVERIFIED_LABEL}, acotado a {MAX_MODEL_TEXT_CHARS} caracteres por "
        f"fragmento): estructura: «{model_text(structure.reasoning)}»; cuantitativo: "
        f"«{model_text(quant.reasoning)}»; auditor: «{model_text(verdict.rationale)}»."
    )


def build_trade_signal(
    *,
    analysis_id: uuid.UUID,
    instrument: InstrumentSchema,
    proposal: ProposedSignal,
    guard: GuardDecision,
    verdict: RiskVerdict | None,
    structure: MarketStructureReport,
    quant: QuantAlphaReport,
    created_at: datetime | None = None,
) -> TradeSignalSchema:
    """Señal canónica desde propuesta + guardas + veredicto del auditor.

    Con guardas aprobadas el veredicto es obligatorio (`ValueError` si falta): una señal nunca
    se aprueba sin auditar. El R:R sale de las guardas (truncado a 4 decimales, nunca al alza).
    """
    if guard.approved and verdict is None:
        raise ValueError("Las guardas aprobaron pero falta el veredicto del auditor")
    status = final_status(guard, verdict)
    rr = guard.rr if guard.rr is not None else proposal.rr
    return TradeSignalSchema(
        id=uuid.uuid4(),
        analysis_id=analysis_id,
        symbol=instrument.symbol,
        asset_class=instrument.asset_class,
        timeframe=proposal.timeframe,
        direction=proposal.direction,
        entry=proposal.entry,
        stop_loss=proposal.stop_loss,
        take_profit=proposal.take_profit,
        rr=rr.quantize(_RR_QUANTUM, rounding=ROUND_DOWN),
        size=guard.size,
        status=status,
        regime=quant.regime,
        rationale=_rationale(status, proposal, guard, verdict, structure, quant),
        veto_reasons=list(guard.reasons),
        created_at=created_at or datetime.now(UTC),
    )


async def persist_signal(
    session: AsyncSession, signal: TradeSignalSchema, instrument_id: int
) -> None:
    """Inserta la señal (APPROVED o REJECTED) sin `commit`: lo hace el orquestador (D96)."""
    await signals_repo.insert_signal(session, signal, instrument_id)
