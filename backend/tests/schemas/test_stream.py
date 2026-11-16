"""Tests de esquemas de eventos de stream."""

from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.enums import (
    AssetClass,
    Direction,
    RegimeLabel,
    SignalStatus,
    Timeframe,
)
from app.schemas.risk import PositionSizeResult
from app.schemas.signals import TradeSignalSchema
from app.schemas.stream import (
    SignalAlertEvent,
    StreamErrorEvent,
    StreamEventAdapter,
    StreamEventEnvelope,
    TickUpdateEvent,
)


def _trade_signal() -> TradeSignalSchema:
    return TradeSignalSchema(
        id=uuid4(),
        analysis_id=uuid4(),
        symbol="BTC/USDT",
        asset_class=AssetClass.CRYPTO,
        timeframe=Timeframe.H1,
        direction=Direction.LONG,
        entry=Decimal("60000"),
        stop_loss=Decimal("59800"),
        take_profit=Decimal("60400"),
        rr=Decimal("2.0"),
        size=PositionSizeResult(
            units=Decimal("0.5"),
            risk_amount=Decimal("100"),
            risk_pct=Decimal("0.01"),
            stop_distance=Decimal("200"),
            notional=Decimal("30000"),
        ),
        status=SignalStatus.APPROVED,
        regime=RegimeLabel.TRENDING,
        rationale="ok",
        veto_reasons=[],
        created_at=__import__("datetime").datetime(2024, 1, 1, tzinfo=__import__("datetime").UTC),
    )


class TestTickUpdateEvent:
    def test_valido(self) -> None:
        tick = TickUpdateEvent(
            type="tick",
            symbol="BTC/USDT",
            timeframe=Timeframe.H1,
            price="60000.50",
            provisional=True,
        )
        assert tick.type == "tick"
        assert tick.provisional is True
        assert tick.price == "60000.50"

    def test_precio_como_cadena_en_json(self) -> None:
        tick = TickUpdateEvent(
            type="tick",
            symbol="BTC/USDT",
            timeframe=Timeframe.H1,
            price="60000.50",
            provisional=True,
        )
        dump = tick.model_dump(mode="json")
        assert isinstance(dump["price"], str)
        assert dump["price"] == "60000.50"

    def test_provisional_siempre_true(self) -> None:
        tick = TickUpdateEvent(
            type="tick",
            symbol="BTC/USDT",
            timeframe=Timeframe.H1,
            price="60000.50",
            provisional=True,
        )
        assert tick.provisional is True

    def test_provisional_false_rechazado(self) -> None:
        with pytest.raises(ValidationError):
            TickUpdateEvent(
                type="tick",
                symbol="BTC/USDT",
                timeframe=Timeframe.H1,
                price="60000.50",
                provisional=False,  # type: ignore[arg-type]
            )

    def test_precio_formato_invalido(self) -> None:
        with pytest.raises(ValidationError):
            TickUpdateEvent(
                type="tick",
                symbol="BTC/USDT",
                timeframe=Timeframe.H1,
                price="abc",
                provisional=True,
            )

    def test_inmutable(self) -> None:
        tick = TickUpdateEvent(
            type="tick",
            symbol="BTC/USDT",
            timeframe=Timeframe.H1,
            price="60000.50",
            provisional=True,
        )
        with pytest.raises(ValidationError):
            tick.price = "1"  # type: ignore[misc]


class TestSignalAlertEvent:
    def test_solo_acepta_aprobada(self) -> None:
        signal = _trade_signal()
        event = SignalAlertEvent(type="signal", signal=signal)
        assert event.signal.status is SignalStatus.APPROVED

    def test_rechaza_no_aprobada(self) -> None:
        signal = _trade_signal()
        signal_rejected = signal.model_copy(update={"status": SignalStatus.REJECTED})
        with pytest.raises(ValidationError):
            SignalAlertEvent(type="signal", signal=signal_rejected)

    def test_signal_viaja_como_cadena_en_json(self) -> None:
        signal = _trade_signal()
        event = SignalAlertEvent(type="signal", signal=signal)
        dump = event.model_dump(mode="json")
        assert isinstance(dump["signal"]["entry"], str)
        assert dump["signal"]["entry"] == "60000"

    def test_inmutable(self) -> None:
        signal = _trade_signal()
        event = SignalAlertEvent(type="signal", signal=signal)
        with pytest.raises(ValidationError):
            event.type = "tick"  # type: ignore[misc]


class TestStreamErrorEvent:
    def test_valido(self) -> None:
        err = StreamErrorEvent(type="error", message="Error de conexión")
        assert err.message == "Error de conexión"

    def test_inmutable(self) -> None:
        err = StreamErrorEvent(type="error", message="Error")
        with pytest.raises(ValidationError):
            err.message = "otro"  # type: ignore[misc]


class TestStreamEventDiscriminatedUnion:
    def test_discrimina_por_type_tick(self) -> None:
        data = {
            "type": "tick",
            "symbol": "BTC/USDT",
            "timeframe": "1h",
            "price": "60000",
            "provisional": True,
        }
        event = StreamEventAdapter.validate_python(data)
        assert isinstance(event, TickUpdateEvent)
        assert event.type == "tick"

    def test_discrimina_por_type_signal(self) -> None:
        signal = _trade_signal()
        data = {"type": "signal", "signal": signal.model_dump(mode="python")}
        event = StreamEventAdapter.validate_python(data)
        assert isinstance(event, SignalAlertEvent)
        assert event.type == "signal"

    def test_discrimina_por_type_error(self) -> None:
        data = {"type": "error", "message": "algo fallo"}
        event = StreamEventAdapter.validate_python(data)
        assert isinstance(event, StreamErrorEvent)
        assert event.type == "error"

    def test_type_desconocido_rechazado(self) -> None:
        data = {"type": "unknown", "foo": "bar"}
        with pytest.raises(ValidationError):
            StreamEventAdapter.validate_python(data)

    def test_type_ausente_rechazado(self) -> None:
        data = {"symbol": "BTC/USDT", "timeframe": "1h", "price": "60000", "provisional": True}
        with pytest.raises(ValidationError):
            StreamEventAdapter.validate_python(data)


class TestStreamEventEnvelope:
    def test_ida_y_vuelta_json(self) -> None:
        signal = _trade_signal()
        original = StreamEventEnvelope(root=SignalAlertEvent(type="signal", signal=signal))
        json_str = original.model_dump_json()
        restored = StreamEventEnvelope.model_validate_json(json_str)
        assert restored == original

    def test_tick_ida_y_vuelta(self) -> None:
        original = StreamEventEnvelope(
            root=TickUpdateEvent(
                type="tick",
                symbol="BTC/USDT",
                timeframe=Timeframe.H1,
                price="60000",
                provisional=True,
            )
        )
        restored = StreamEventEnvelope.model_validate_json(original.model_dump_json())
        assert restored == original

    def test_error_ida_y_vuelta(self) -> None:
        original = StreamEventEnvelope(root=StreamErrorEvent(type="error", message="fallo"))
        restored = StreamEventEnvelope.model_validate_json(original.model_dump_json())
        assert restored == original

    def test_extra_en_root_pasa_validacion(self) -> None:
        # RootModel no soporta extra="forbid"; los campos extra en root se ignoran
        env = StreamEventEnvelope.model_validate(
            {
                "type": "tick",
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                "price": "60000",
                "provisional": True,
            }
        )
        assert isinstance(env.root, TickUpdateEvent)


class TestExtraForbid:
    def test_tick_extra_forbid(self) -> None:
        with pytest.raises(ValidationError, match="Extra inputs"):
            TickUpdateEvent(
                type="tick",
                symbol="BTC/USDT",
                timeframe=Timeframe.H1,
                price="60000",
                provisional=True,
                campo_extra=1,
            )

    def test_signal_extra_forbid(self) -> None:
        signal = _trade_signal()
        with pytest.raises(ValidationError, match="Extra inputs"):
            SignalAlertEvent(type="signal", signal=signal, campo_extra=1)

    def test_error_extra_forbid(self) -> None:
        with pytest.raises(ValidationError, match="Extra inputs"):
            StreamErrorEvent(type="error", message="fallo", campo_extra=1)
