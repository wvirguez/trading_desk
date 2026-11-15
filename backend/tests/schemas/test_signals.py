import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.enums import (
    AssetClass,
    Direction,
    RegimeLabel,
    SignalStatus,
    Timeframe,
    VetoReason,
)
from app.schemas.risk import PositionSizeResult
from app.schemas.signals import AUDITOR_REJECTION_MARKER, ProposedSignal, TradeSignalSchema

D = Decimal


def _size() -> PositionSizeResult:
    return PositionSizeResult(
        units=D("0.5"),
        risk_amount=D("100"),
        risk_pct=D("0.01"),
        stop_distance=D("200"),
        notional=D("30000"),
    )


def _proposed(**over: Any) -> ProposedSignal:
    data: dict[str, Any] = {
        "symbol": "BTCUSDT",
        "timeframe": Timeframe.H1,
        "direction": Direction.LONG,
        "entry": D("60000"),
        "stop_loss": D("59800"),
        "take_profit": D("60400"),
        "rr": D("2.0"),
        "source": "entrada=borde FVG; SL=invalidación-0.5ATR; TP=2R",
    }
    data.update(over)
    return ProposedSignal(**data)


def _signal(**over: Any) -> TradeSignalSchema:
    data: dict[str, Any] = {
        "id": uuid4(),
        "analysis_id": uuid4(),
        "symbol": "BTCUSDT",
        "asset_class": AssetClass.CRYPTO,
        "timeframe": Timeframe.H1,
        "direction": Direction.LONG,
        "entry": D("60000"),
        "stop_loss": D("59800"),
        "take_profit": D("60400"),
        "rr": D("2.0"),
        "size": _size(),
        "status": SignalStatus.APPROVED,
        "regime": RegimeLabel.TRENDING,
        "rationale": "ok",
        "veto_reasons": [],
        "created_at": datetime(2024, 1, 1, tzinfo=UTC),
    }
    data.update(over)
    return TradeSignalSchema(**data)


SHORT = {"direction": Direction.SHORT, "stop_loss": D("60200"), "take_profit": D("59600")}


def test_propuesta_long_y_short_validas() -> None:
    assert _proposed().direction is Direction.LONG
    assert _proposed(**SHORT).direction is Direction.SHORT


@pytest.mark.parametrize(
    "over",
    [
        {"stop_loss": D("60000")},  # SL == entrada
        {"stop_loss": D("60100")},  # SL por encima en LONG
        {"take_profit": D("59900")},  # TP por debajo en LONG
        {**SHORT, "stop_loss": D("59800")},  # SHORT con SL por debajo
        {**SHORT, "take_profit": D("60300")},  # SHORT con TP por encima
        {"entry": D("0"), "stop_loss": D("-1")},
        {"rr": D("0")},
    ],
)
def test_propuesta_rechaza_niveles_incoherentes(over: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _proposed(**over)


def test_mensaje_de_niveles_en_espanol() -> None:
    with pytest.raises(ValidationError, match="En LONG se exige stop_loss < entry < take_profit"):
        _proposed(stop_loss=D("60100"))
    with pytest.raises(ValidationError, match="En SHORT se exige take_profit < entry < stop_loss"):
        _proposed(direction=Direction.SHORT)


def test_senal_aprobada_valida() -> None:
    assert _signal().status is SignalStatus.APPROVED
    assert _signal(**SHORT).direction is Direction.SHORT


def test_senal_rechaza_niveles_incoherentes() -> None:
    with pytest.raises(ValidationError, match="En LONG"):
        _signal(stop_loss=D("60500"))
    with pytest.raises(ValidationError, match="En SHORT"):
        _signal(direction=Direction.SHORT)


def test_aprobada_requiere_size() -> None:
    with pytest.raises(ValidationError, match="requiere size"):
        _signal(size=None)


def test_aprobada_no_admite_veto_reasons() -> None:
    with pytest.raises(ValidationError, match="no puede tener veto_reasons"):
        _signal(veto_reasons=[VetoReason.RR_BELOW_MIN])


def test_rechazada_con_veto_reasons() -> None:
    s = _signal(status=SignalStatus.REJECTED, size=None, veto_reasons=[VetoReason.RR_BELOW_MIN])
    assert s.status is SignalStatus.REJECTED


def test_rechazada_por_auditor_en_rationale() -> None:
    s = _signal(
        status=SignalStatus.REJECTED,
        rationale=f"{AUDITOR_REJECTION_MARKER} liquidez baja",
    )
    assert s.veto_reasons == []


def test_rechazada_sin_motivo_alguno_falla() -> None:
    with pytest.raises(ValidationError, match="REJECTED requiere veto_reasons"):
        _signal(status=SignalStatus.REJECTED, size=None, rationale="sin más")


@pytest.mark.parametrize("status", [SignalStatus.PENDING, SignalStatus.EXECUTED])
def test_otros_estados_sin_reglas_adicionales(status: SignalStatus) -> None:
    assert _signal(status=status, size=None).status is status


def test_decimal_viaja_como_cadena_y_ida_y_vuelta() -> None:
    s = _signal()
    payload = json.loads(s.model_dump_json())
    assert payload["entry"] == "60000"
    assert payload["rr"] == "2.0"
    assert payload["size"]["units"] == "0.5"
    assert TradeSignalSchema.model_validate_json(s.model_dump_json()) == s
    assert json.loads(_proposed().model_dump_json())["take_profit"] == "60400"


def test_extra_forbid() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        _proposed(campo_inventado=1)
    with pytest.raises(ValidationError, match="Extra inputs"):
        _signal(campo_inventado=1)


def test_inmutabilidad() -> None:
    with pytest.raises(ValidationError, match="frozen"):
        _proposed().entry = D("1")  # type: ignore[misc]
    with pytest.raises(ValidationError, match="frozen"):
        _signal().status = SignalStatus.REJECTED  # type: ignore[misc]
