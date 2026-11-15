"""Veto determinista y auditor de riesgo (3.7, D94).

El código decide: `final_status` es el único lugar donde se aprueba una señal. El LLM solo puede
mantener o endurecer una decisión ya aprobada por las guardas; nunca la reabre ni calcula riesgo.
"""

from pydantic_ai import Agent, UsageLimits

from app.agents.deps import AgentDeps
from app.agents.prompts import RISK_AUDITOR_PROMPT
from app.agents.runner import AgentRun, run_agent
from app.core.config import Settings
from app.schemas.agents import AuditorOutput, RiskVerdict
from app.schemas.enums import AuditDecision, SignalStatus
from app.schemas.risk import GuardDecision
from app.schemas.signals import (
    AUDITOR_REJECTION_MARKER,
    UNVERIFIED_LABEL,
    ProposedSignal,
    model_text,
)

risk_auditor_agent: Agent[AgentDeps, AuditorOutput] = Agent(
    output_type=AuditorOutput,
    deps_type=AgentDeps,
    system_prompt=RISK_AUDITOR_PROMPT,
    retries=2,
    name="risk_auditor",
)


def final_status(guard: GuardDecision, verdict: RiskVerdict | None) -> SignalStatus:
    """Único lugar donde se decide aprobar: guardas aprobadas Y auditor en `APPROVE`."""
    if guard.approved and verdict is not None and verdict.decision is AuditDecision.APPROVE:
        return SignalStatus.APPROVED
    return SignalStatus.REJECTED


def auditor_rejection_rationale(verdict: RiskVerdict) -> str:
    """Rationale de una señal rechazada por el auditor; lleva `AUDITOR_REJECTION_MARKER`.

    El texto del auditor es prosa del LLM: va etiquetado como no verificado y acotado (D112).
    """
    detail = model_text(verdict.rationale)
    if verdict.concerns:
        concerns = model_text("; ".join(verdict.concerns))
        detail = f"{detail} Preocupaciones: {concerns}".strip()
    return f"{AUDITOR_REJECTION_MARKER} (texto del modelo, {UNVERIFIED_LABEL}) {detail}".rstrip()


def build_audit_prompt(guard: GuardDecision, proposal: ProposedSignal) -> str:
    return (
        "Audita la siguiente señal.\n"
        f"Propuesta (JSON): {proposal.model_dump_json()}\n"
        f"Decisión de las guardas deterministas (JSON): {guard.model_dump_json()}"
    )


async def run_risk_audit(
    guard: GuardDecision,
    proposal: ProposedSignal,
    deps: AgentDeps,
    *,
    settings: Settings,
    limits: UsageLimits | None = None,
) -> tuple[RiskVerdict | None, AgentRun[AuditorOutput] | None]:
    """Invoca al auditor solo si las guardas aprobaron (D94).

    Con veto determinista devuelve `(None, None)` sin llamar al modelo. En otro caso el
    `RiskVerdict` se ensambla aquí: `deterministic` es la decisión de las guardas.
    """
    if not guard.approved:
        return None, None
    run = await run_agent(
        risk_auditor_agent,
        build_audit_prompt(guard, proposal),
        deps,
        limits,
        settings=settings,
    )
    out = run.output
    verdict = RiskVerdict(
        decision=out.decision,
        deterministic=guard,
        concerns=list(out.concerns),
        rationale=out.rationale,
    )
    return verdict, run
