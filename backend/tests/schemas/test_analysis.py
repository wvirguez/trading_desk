import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError

from app.schemas.agents import MarketStructureReport, TimeframeStructure
from app.schemas.analysis import (
    AgentReportSchema,
    AnalysisCompleted,
    AnalysisEvent,
    AnalysisFailed,
    AnalysisStarted,
    AnalyzeRequest,
    StepCompleted,
    StepFailed,
    StepStarted,
    StepUsage,
)
from app.schemas.enums import AnalysisOutcome, AnalysisStep, Bias, Timeframe
from app.schemas.risk import GuardDecision

ADAPTER: TypeAdapter[AnalysisEvent] = TypeAdapter(AnalysisEvent)
NOW = datetime(2024, 1, 1, tzinfo=UTC)


def test_request_defaults() -> None:
    r = AnalyzeRequest(symbol="BTCUSDT")
    assert r.timeframe is Timeframe.H1
    assert r.timeframes == [Timeframe.M15, Timeframe.H1, Timeframe.H4, Timeframe.D1]


def test_request_defaults_no_se_comparten() -> None:
    assert AnalyzeRequest(symbol="A").timeframes is not AnalyzeRequest(symbol="B").timeframes


@pytest.mark.parametrize("symbol", ["", "   "])
def test_request_symbol_no_vacio(symbol: str) -> None:
    with pytest.raises(ValidationError, match="symbol no puede estar vacío"):
        AnalyzeRequest(symbol=symbol)


def test_request_timeframe_debe_estar_en_timeframes() -> None:
    with pytest.raises(ValidationError, match="debe estar incluido en timeframes"):
        AnalyzeRequest(symbol="X", timeframe=Timeframe.M5)


def test_request_rechaza_marcos_repetidos() -> None:
    with pytest.raises(ValidationError, match="repetir marcos"):
        AnalyzeRequest(symbol="X", timeframes=[Timeframe.H1, Timeframe.H1, Timeframe.H4])


def test_request_extra_forbid_e_inmutable() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        AnalyzeRequest.model_validate({"symbol": "X", "otro": 1})
    with pytest.raises(ValidationError, match="frozen"):
        AnalyzeRequest(symbol="X").symbol = "Y"  # type: ignore[misc]


def test_step_usage_decimal_como_cadena_y_extra_forbid() -> None:
    u = StepUsage(model="m", input_tokens=10, output_tokens=5, cost_usd=Decimal("0.0123"))
    assert json.loads(u.model_dump_json())["cost_usd"] == "0.0123"
    assert StepUsage().cost_usd is None
    with pytest.raises(ValidationError):
        StepUsage(input_tokens=-1)
    with pytest.raises(ValidationError, match="Extra inputs"):
        StepUsage.model_validate({"otro": 1})
    with pytest.raises(ValidationError, match="frozen"):
        u.latency_ms = 3  # type: ignore[misc]


def _structure() -> MarketStructureReport:
    def tf(t: Timeframe) -> TimeframeStructure:
        return TimeframeStructure(
            timeframe=t,
            bias=Bias.BULLISH,
            key_levels=[Decimal("1.5")],
            open_fvg_ts=[NOW],
            comment="",
        )

    return MarketStructureReport(
        symbol="BTCUSDT",
        entry_timeframe=Timeframe.H1,
        timeframes=[tf(Timeframe.H1), tf(Timeframe.H4)],
        htf_alignment=Bias.BULLISH,
        invalidation_level=Decimal("1.25"),
        reasoning="r",
    )


def _report() -> AgentReportSchema:
    return AgentReportSchema(
        analysis_id=uuid4(),
        symbol="BTCUSDT",
        timeframe=Timeframe.H1,
        outcome=AnalysisOutcome.NO_TRADE,
        structure=_structure(),
        guards=GuardDecision(approved=False, reasons=[], messages=["x"], rr=Decimal("1.5")),
        usage=StepUsage(model="m", input_tokens=3, cost_usd=Decimal("0.5")),
        warnings=["Estado de cartera simulado"],
    )


def test_agent_report_ida_y_vuelta_json() -> None:
    r = _report()
    payload = json.loads(r.model_dump_json())
    assert payload["guards"]["rr"] == "1.5"
    assert payload["usage"]["cost_usd"] == "0.5"
    assert payload["structure"]["invalidation_level"] == "1.25"
    assert payload["quant"] is None
    assert AgentReportSchema.model_validate_json(r.model_dump_json()) == r


def test_agent_report_extra_forbid_e_inmutable() -> None:
    payload = json.loads(_report().model_dump_json())
    with pytest.raises(ValidationError, match="Extra inputs"):
        AgentReportSchema.model_validate({**payload, "otro": 1})
    with pytest.raises(ValidationError, match="frozen"):
        _report().outcome = AnalysisOutcome.SIGNAL_APPROVED  # type: ignore[misc]


def test_analysis_event_discrimina_por_event() -> None:
    aid = uuid4()
    usage = StepUsage(input_tokens=1)
    eventos = [
        AnalysisStarted(
            analysis_id=aid,
            seq=0,
            symbol="BTCUSDT",
            timeframe=Timeframe.H1,
            timeframes=[Timeframe.H1, Timeframe.H4],
            started_at=NOW,
        ),
        StepStarted(analysis_id=aid, seq=1, step=AnalysisStep.STRUCTURE),
        StepCompleted(
            analysis_id=aid, seq=2, step=AnalysisStep.STRUCTURE, output={"a": [1, "b"]}, usage=usage
        ),
        StepFailed(analysis_id=aid, seq=3, step=AnalysisStep.QUANT, error="falló"),
        AnalysisCompleted(analysis_id=aid, seq=4, report=_report()),
        AnalysisFailed(analysis_id=aid, seq=5, error="tope de tokens", step=AnalysisStep.QUANT),
    ]
    esperados = [
        "analysis_started",
        "step_started",
        "step_completed",
        "step_failed",
        "analysis_completed",
        "analysis_failed",
    ]
    for ev, nombre in zip(eventos, esperados, strict=True):
        data = json.loads(ev.model_dump_json())
        assert data["event"] == nombre
        assert data["seq"] == ev.seq
        assert data["analysis_id"] == str(aid)
        assert ADAPTER.validate_json(ev.model_dump_json()) == ev
        assert type(ADAPTER.validate_python(data)) is type(ev)


def test_analysis_event_rechaza_discriminador_desconocido_o_ausente() -> None:
    aid = str(uuid4())
    with pytest.raises(ValidationError, match="does not match any of the expected tags"):
        ADAPTER.validate_python({"event": "otro", "analysis_id": aid, "seq": 0})
    with pytest.raises(ValidationError, match="Unable to extract tag"):
        ADAPTER.validate_python({"analysis_id": aid, "seq": 0})


def test_analysis_event_campos_segun_tipo_y_seq_no_negativa() -> None:
    aid = str(uuid4())
    with pytest.raises(ValidationError):  # step_started exige step
        ADAPTER.validate_python({"event": "step_started", "analysis_id": aid, "seq": 0})
    with pytest.raises(ValidationError):
        ADAPTER.validate_python(
            {"event": "step_started", "analysis_id": aid, "seq": -1, "step": "QUANT"}
        )
    with pytest.raises(ValidationError, match="Extra inputs"):
        ADAPTER.validate_python(
            {"event": "step_started", "analysis_id": aid, "seq": 0, "step": "QUANT", "x": 1}
        )
