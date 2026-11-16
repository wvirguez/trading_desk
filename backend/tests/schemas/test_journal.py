import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.enums import (
    Direction,
    JournalOutcome,
    RegimeLabel,
    SignalStatus,
    Timeframe,
    VetoReason,
)
from app.schemas.journal import JournalEntrySchema, JournalSchema, JournalSummarySchema

D = Decimal
T0 = datetime(2024, 1, 1, 10, tzinfo=UTC)
T2 = datetime(2024, 1, 1, 12, tzinfo=UTC)

WIN = {
    "outcome": JournalOutcome.WIN,
    "order_id": uuid4(),
    "fill_price": D("60000"),
    "exit_price": D("60400"),
    "realized_pnl": D("200"),
    "r_multiple": D("2"),
    "closed_at": T2,
}


def _entry(**over: Any) -> JournalEntrySchema:
    data: dict[str, Any] = {
        "signal_id": uuid4(),
        "analysis_id": uuid4(),
        "created_at": T0,
        "symbol": "BTCUSDT",
        "timeframe": Timeframe.H1,
        "direction": Direction.LONG,
        "signal_status": SignalStatus.APPROVED,
        "regime": RegimeLabel.TRENDING,
        "entry": D("60000"),
        "stop_loss": D("59800"),
        "take_profit": D("60400"),
        "rr": D("2.0"),
        "risk_amount": D("100"),
        "veto_reasons": [],
        "rationale": "ok",
        "outcome": JournalOutcome.NOT_EXECUTED,
    }
    data.update(over)
    return JournalEntrySchema(**data)


def _summary(**over: Any) -> JournalSummarySchema:
    data: dict[str, Any] = {
        "n_signals": 3,
        "n_approved": 2,
        "n_rejected": 1,
        "n_executed": 2,
        "n_closed": 2,
        "n_wins": 1,
        "n_losses": 1,
        "win_rate": 0.5,
        "total_pnl": D("100"),
        "expectancy_r": 0.5,
        "avg_rr_emitted": 2.0,
        "avg_r_realized": 0.5,
        "warnings": [
            "Muestra pequeña: 2 operaciones cerradas (< 30); las métricas no son concluyentes."
        ],
    }
    data.update(over)
    return JournalSummarySchema(**data)


def test_entrada_no_ejecutada_valida_incluida_rechazada() -> None:
    assert _entry().order_id is None
    rej = _entry(
        signal_status=SignalStatus.REJECTED,
        risk_amount=None,
        veto_reasons=[VetoReason.RR_BELOW_MIN],
    )
    assert rej.outcome is JournalOutcome.NOT_EXECUTED


def test_entradas_con_orden_validas() -> None:
    oid = uuid4()
    assert _entry(outcome=JournalOutcome.PENDING_FILL, order_id=oid)
    assert _entry(outcome=JournalOutcome.OPEN, order_id=oid, fill_price=D("60000"))
    assert _entry(**WIN).outcome is JournalOutcome.WIN
    loss = {
        **WIN,
        "outcome": JournalOutcome.LOSS,
        "exit_price": D("59800"),
        "realized_pnl": D("-100"),
        "r_multiple": D("-1"),
    }
    assert _entry(**loss).r_multiple == D("-1")


def test_no_ejecutada_sin_datos_de_orden() -> None:
    with pytest.raises(ValidationError, match="NOT_EXECUTED no puede tener order_id"):
        _entry(order_id=uuid4())
    with pytest.raises(ValidationError, match="NOT_EXECUTED no puede tener datos de orden"):
        _entry(fill_price=D("1"))


@pytest.mark.parametrize(
    "outcome", [JournalOutcome.PENDING_FILL, JournalOutcome.OPEN, JournalOutcome.WIN]
)
def test_con_orden_exige_order_id(outcome: JournalOutcome) -> None:
    with pytest.raises(ValidationError, match="requiere order_id"):
        _entry(outcome=outcome)


@pytest.mark.parametrize("falta", ["fill_price", "exit_price", "realized_pnl", "closed_at"])
def test_cerrada_exige_datos_de_cierre(falta: str) -> None:
    with pytest.raises(ValidationError, match=f"requiere .*{falta}"):
        _entry(**{**WIN, falta: None})


def test_pending_con_fill_price_falla() -> None:
    with pytest.raises(ValidationError, match="PENDING_FILL no puede tener fill_price"):
        _entry(outcome=JournalOutcome.PENDING_FILL, order_id=uuid4(), fill_price=D("1"))


def test_open_con_realized_pnl_falla() -> None:
    with pytest.raises(ValidationError, match="no puede tener datos de cierre"):
        _entry(
            outcome=JournalOutcome.OPEN,
            order_id=uuid4(),
            fill_price=D("60000"),
            realized_pnl=D("1"),
        )


def test_resumen_admite_metricas_none() -> None:
    s = _summary(
        n_closed=0, n_wins=0, n_losses=0, win_rate=None, expectancy_r=None,
        avg_rr_emitted=None, avg_r_realized=None, total_pnl=D("0"),
    )  # fmt: skip
    assert s.win_rate is None and s.expectancy_r is None and s.avg_r_realized is None
    payload = json.loads(s.model_dump_json())
    assert payload["win_rate"] is None
    assert payload["expectancy_r"] is None
    assert payload["avg_r_realized"] is None
    assert JournalSummarySchema.model_validate_json(s.model_dump_json()) == s


def test_resumen_defaults_none_y_contadores() -> None:
    s = JournalSummarySchema(
        n_signals=0, n_approved=0, n_rejected=0, n_executed=0, n_closed=0,
        n_wins=0, n_losses=0, total_pnl=D("0"),
    )  # fmt: skip
    assert s.win_rate is None and s.warnings == []
    with pytest.raises(ValidationError, match="n_signals no puede ser negativo"):
        _summary(n_signals=-1)
    with pytest.raises(ValidationError, match="n_wins \\+ n_losses debe igualar n_closed"):
        _summary(n_closed=5)


def test_decimales_como_cadena_y_ida_y_vuelta() -> None:
    j = JournalSchema(summary=_summary(), entries=[_entry(**WIN), _entry()])
    payload = json.loads(j.model_dump_json())
    assert payload["summary"]["total_pnl"] == "100"
    e = payload["entries"][0]
    for campo in (
        "entry",
        "rr",
        "risk_amount",
        "fill_price",
        "exit_price",
        "realized_pnl",
        "r_multiple",
    ):
        assert isinstance(e[campo], str), campo
    assert e["realized_pnl"] == "200"
    assert payload["entries"][1]["exit_price"] is None
    assert JournalSchema.model_validate_json(j.model_dump_json()) == j


def test_extra_forbid() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        _entry(campo_inventado=1)
    with pytest.raises(ValidationError, match="Extra inputs"):
        _summary(campo_inventado=1)
    with pytest.raises(ValidationError, match="Extra inputs"):
        JournalSchema(summary=_summary(), entries=[], campo_inventado=1)  # type: ignore[call-arg]


def test_inmutabilidad() -> None:
    with pytest.raises(ValidationError, match="frozen"):
        _entry().outcome = JournalOutcome.WIN  # type: ignore[misc]
    with pytest.raises(ValidationError, match="frozen"):
        _summary().n_signals = 9  # type: ignore[misc]
    with pytest.raises(ValidationError, match="frozen"):
        JournalSchema(summary=_summary(), entries=[]).entries = []  # type: ignore[misc]
