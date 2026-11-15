"""Propiedad de D94: APPROVED solo si las guardas y el auditor aprueban."""

from hypothesis import given, settings
from hypothesis import strategies as st

from app.agents.risk_auditor import final_status
from app.schemas.agents import RiskVerdict
from app.schemas.enums import AuditDecision, SignalStatus, VetoReason
from app.schemas.risk import GuardDecision


@st.composite
def guards(draw: st.DrawFn) -> GuardDecision:
    approved = draw(st.booleans())
    reasons = [] if approved else draw(st.lists(st.sampled_from(VetoReason), max_size=3))
    return GuardDecision(approved=approved, reasons=reasons, messages=[])


@st.composite
def verdicts(draw: st.DrawFn, guard: GuardDecision) -> RiskVerdict | None:
    if draw(st.booleans()):
        return None
    return RiskVerdict(
        decision=draw(st.sampled_from(AuditDecision)),
        deterministic=draw(st.one_of(st.just(guard), guards())),
        concerns=[],
        rationale="x",
    )


@settings(derandomize=True, max_examples=200)
@given(data=st.data())
def test_approved_only_if_both_approve(data: st.DataObject) -> None:
    guard = data.draw(guards())
    verdict = data.draw(verdicts(guard))
    status = final_status(guard, verdict)
    both = guard.approved and verdict is not None and verdict.decision is AuditDecision.APPROVE
    assert (status is SignalStatus.APPROVED) == both
    assert status in (SignalStatus.APPROVED, SignalStatus.REJECTED)
