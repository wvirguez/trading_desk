import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.agents import (
    MAX_REASONING_CHARS,
    MarketStructureReport,
    QuantAlphaReport,
    RiskVerdict,
    TimeframeStructure,
)
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

TS = datetime(2024, 1, 1, tzinfo=UTC)


def _tf(timeframe: Timeframe = Timeframe.H1) -> TimeframeStructure:
    return TimeframeStructure(
        timeframe=timeframe,
        bias=Bias.BULLISH,
        last_event=StructureEventType.BOS,
        key_levels=[Decimal("100.5")],
        open_fvg_ts=[TS],
        comment="BOS alcista",
    )


def _report(**over: Any) -> MarketStructureReport:
    data: dict[str, Any] = {
        "symbol": "BTCUSDT",
        "entry_timeframe": Timeframe.H1,
        "timeframes": [_tf(Timeframe.H1), _tf(Timeframe.H4)],
        "htf_alignment": Bias.BULLISH,
        "zone_ts": TS,
        "invalidation_level": Decimal("99.25"),
        "reasoning": "Alineación alcista",
    }
    data.update(over)
    return MarketStructureReport(**data)


def _stats() -> RegimeStats:
    return RegimeStats(hurst=0.6, adf_pvalue=0.4, zscore=1.2, volatility_ratio=1.0, n_obs=500)


def _quant(**over: Any) -> QuantAlphaReport:
    data: dict[str, Any] = {
        "symbol": "BTCUSDT",
        "timeframe": Timeframe.H1,
        "regime": RegimeLabel.TRENDING,
        "stats": _stats(),
        "playbook": Playbook.TREND_FOLLOWING,
        "kelly": KellyResult(full_kelly=0.2, fraction=0.05, capped=True),
        "reasoning": "Hurst alto",
    }
    data.update(over)
    return QuantAlphaReport(**data)


def test_informe_valido_y_decimal_como_cadena_en_json() -> None:
    payload = json.loads(_report().model_dump_json())
    assert payload["invalidation_level"] == "99.25"
    assert payload["timeframes"][0]["key_levels"] == ["100.5"]


def test_timeframes_exige_al_menos_dos() -> None:
    with pytest.raises(ValidationError, match="at least 2"):
        _report(timeframes=[_tf()])


def test_timeframes_rechaza_marcos_repetidos() -> None:
    with pytest.raises(ValidationError, match="repetir marcos"):
        _report(timeframes=[_tf(Timeframe.H1), _tf(Timeframe.H1)])


def test_reasoning_acotado() -> None:
    _report(reasoning="x" * MAX_REASONING_CHARS)
    with pytest.raises(ValidationError, match="at most 1500"):
        _report(reasoning="x" * (MAX_REASONING_CHARS + 1))
    with pytest.raises(ValidationError, match="at most 1500"):
        _quant(reasoning="x" * (MAX_REASONING_CHARS + 1))


def test_extra_forbid_en_todos_los_esquemas() -> None:
    guard = GuardDecision(approved=True, reasons=[], messages=[])
    verdict = {"decision": "APPROVE", "deterministic": guard, "concerns": [], "rationale": "ok"}
    with pytest.raises(ValidationError, match="Extra inputs"):
        _report(campo_inventado=1)
    with pytest.raises(ValidationError, match="Extra inputs"):
        _quant(campo_inventado=1)
    with pytest.raises(ValidationError, match="Extra inputs"):
        RiskVerdict(**verdict, campo_inventado=1)
    with pytest.raises(ValidationError, match="Extra inputs"):
        TimeframeStructure(
            timeframe=Timeframe.H1,
            bias=Bias.NEUTRAL,
            key_levels=[],
            open_fvg_ts=[],
            comment="",
            campo_inventado=1,
        )


def test_inmutabilidad() -> None:
    with pytest.raises(ValidationError, match="frozen"):
        _report().symbol = "ETHUSDT"  # type: ignore[misc]
    with pytest.raises(ValidationError, match="frozen"):
        _quant().playbook = Playbook.NO_TRADE  # type: ignore[misc]
    with pytest.raises(ValidationError, match="frozen"):
        _tf().bias = Bias.BEARISH  # type: ignore[misc]


def test_quant_report_kelly_opcional() -> None:
    assert _quant(kelly=None).kelly is None


def test_risk_verdict_ida_y_vuelta() -> None:
    guard = GuardDecision(approved=True, reasons=[], messages=[], rr=Decimal("2.0"))
    verdict = RiskVerdict(
        decision=AuditDecision.VETO, deterministic=guard, concerns=["liquidez"], rationale="r"
    )
    assert RiskVerdict.model_validate_json(verdict.model_dump_json()) == verdict
    assert json.loads(verdict.model_dump_json())["deterministic"]["rr"] == "2.0"


def test_decision_invalida_rechazada() -> None:
    with pytest.raises(ValidationError):
        RiskVerdict.model_validate(
            {
                "decision": "MAYBE",
                "deterministic": {"approved": True, "reasons": [], "messages": []},
                "concerns": [],
                "rationale": "",
            }
        )
