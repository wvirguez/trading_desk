"""Tests del auditor de riesgo y del veto determinista con `FunctionModel` (sin red)."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import polars as pl
import pytest
from pydantic import ValidationError
from pydantic_ai import ModelResponse, ToolCallPart
from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.agents.deps import AgentDeps
from app.agents.prompts import RISK_AUDITOR_PROMPT
from app.agents.risk_auditor import (
    auditor_rejection_rationale,
    final_status,
    risk_auditor_agent,
    run_risk_audit,
)
from app.core.config import Settings
from app.schemas.agents import AuditorOutput, RiskVerdict
from app.schemas.enums import (
    AssetClass,
    AuditDecision,
    Direction,
    RegimeLabel,
    SignalStatus,
    Timeframe,
    VetoReason,
)
from app.schemas.risk import GuardDecision, PortfolioState, PositionSizeResult
from app.schemas.signals import AUDITOR_REJECTION_MARKER, ProposedSignal, TradeSignalSchema
from tests.quant._proposal_helpers import SEED

SYMBOL = "EUR/USD"
SETTINGS = Settings(_env_file=None)  # type: ignore[call-arg]
SIZE = PositionSizeResult(
    units=Decimal(1000),
    risk_amount=Decimal(10),
    risk_pct=Decimal("0.1"),
    stop_distance=Decimal("0.01"),
    notional=Decimal(1100),
)
APPROVED = GuardDecision(approved=True, reasons=[], messages=[], rr=Decimal(2), size=SIZE)
VETOED = GuardDecision(
    approved=False,
    reasons=[VetoReason.RR_BELOW_MIN],
    messages=["R:R 1.5 < mínimo"],
    rr=Decimal("1.5"),
)
PROPOSAL = ProposedSignal(
    symbol=SYMBOL,
    timeframe=Timeframe.H1,
    direction=Direction.LONG,
    entry=Decimal("1.1"),
    stop_loss=Decimal("1.09"),
    take_profit=Decimal("1.12"),
    rr=Decimal(2),
    source="prueba",
)


def _deps() -> AgentDeps:
    return AgentDeps(
        instrument=SEED[SYMBOL],
        candles={Timeframe.H1: pl.DataFrame()},
        settings=SETTINGS,
        portfolio=PortfolioState(
            equity=Decimal(10000),
            day_start_equity=Decimal(10000),
            realized_pnl_today=Decimal(0),
            open_positions=[],
        ),
    )


def _model(decision: AuditDecision, prompts: list[str] | None = None) -> FunctionModel:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if prompts is not None:
            for m in messages:
                if isinstance(m, ModelRequest):
                    prompts.extend(
                        p.content
                        for p in m.parts
                        if isinstance(p, UserPromptPart) and isinstance(p.content, str)
                    )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"decision": decision.value, "concerns": ["c1"], "rationale": "r"},
                )
            ]
        )

    return FunctionModel(respond)


def _failing_model() -> FunctionModel:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        raise AssertionError("El auditor no debe invocarse con un veto determinista")

    return FunctionModel(respond)


async def test_auditor_receives_guard_and_proposal() -> None:
    prompts: list[str] = []
    with risk_auditor_agent.override(model=_model(AuditDecision.APPROVE, prompts)):
        verdict, run = await run_risk_audit(APPROVED, PROPOSAL, _deps(), settings=SETTINGS)
    assert verdict is not None and run is not None
    text = "\n".join(prompts)
    assert PROPOSAL.model_dump_json() in text
    assert APPROVED.model_dump_json() in text
    assert RISK_AUDITOR_PROMPT in run.trace["system_prompt"]
    assert verdict.decision is AuditDecision.APPROVE
    assert final_status(APPROVED, verdict) is SignalStatus.APPROVED


async def test_vetoed_guard_does_not_invoke_agent() -> None:
    with risk_auditor_agent.override(model=_failing_model()):
        verdict, run = await run_risk_audit(VETOED, PROPOSAL, _deps(), settings=SETTINGS)
    assert verdict is None and run is None
    assert final_status(VETOED, verdict) is SignalStatus.REJECTED


def test_model_approve_cannot_approve_vetoed() -> None:
    forged = RiskVerdict(
        decision=AuditDecision.APPROVE, deterministic=VETOED, concerns=[], rationale="ok"
    )
    assert final_status(VETOED, forged) is SignalStatus.REJECTED
    assert final_status(VETOED, None) is SignalStatus.REJECTED


async def test_model_veto_on_approved_proposal_rejects() -> None:
    with risk_auditor_agent.override(model=_model(AuditDecision.VETO)):
        verdict, _ = await run_risk_audit(APPROVED, PROPOSAL, _deps(), settings=SETTINGS)
    assert verdict is not None
    assert final_status(APPROVED, verdict) is SignalStatus.REJECTED
    assert verdict.concerns == ["c1"]


async def test_deterministic_comes_from_guards_not_llm() -> None:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        args = {
            "decision": "APPROVE",
            "concerns": [],
            "rationale": "r",
            "deterministic": {"approved": False, "reasons": [], "messages": []},
        }
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, args)])

    # El esquema reducido rechaza `deterministic`; el modelo debe corregirse (reintento).
    calls = 0

    def respond2(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            return respond(messages, info)
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"decision": "APPROVE", "concerns": [], "rationale": "r"},
                )
            ]
        )

    with risk_auditor_agent.override(model=FunctionModel(respond2)):
        verdict, _ = await run_risk_audit(APPROVED, PROPOSAL, _deps(), settings=SETTINGS)
    assert verdict is not None
    assert verdict.deterministic == APPROVED
    assert calls == 2


def test_auditor_output_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        AuditorOutput.model_validate(
            {"decision": "VETO", "concerns": [], "rationale": "x", "deterministic": {}}
        )


def test_rejection_rationale_satisfies_trade_signal_schema() -> None:
    verdict = RiskVerdict(
        decision=AuditDecision.VETO, deterministic=APPROVED, concerns=["a", "b"], rationale="Mal"
    )
    rationale = auditor_rejection_rationale(verdict)
    assert rationale.startswith(AUDITOR_REJECTION_MARKER)
    assert "a; b" in rationale
    signal = TradeSignalSchema(
        id=uuid4(),
        analysis_id=uuid4(),
        symbol=SYMBOL,
        asset_class=AssetClass.FX,
        timeframe=Timeframe.H1,
        direction=Direction.LONG,
        entry=PROPOSAL.entry,
        stop_loss=PROPOSAL.stop_loss,
        take_profit=PROPOSAL.take_profit,
        rr=PROPOSAL.rr,
        size=SIZE,
        status=SignalStatus.REJECTED,
        regime=RegimeLabel.TRENDING,
        rationale=rationale,
        veto_reasons=[],
        created_at=datetime.now(UTC),
    )
    assert signal.status is SignalStatus.REJECTED
