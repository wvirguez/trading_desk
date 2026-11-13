from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.candle import CandleSchema
from app.schemas.enums import Timeframe

TS = datetime(2024, 3, 5, 0, 0, tzinfo=UTC)  # alineado con los 5 timeframes


def make(**overrides: Any) -> CandleSchema:
    data: dict[str, Any] = {
        "symbol": "BTC/USDT",
        "timeframe": Timeframe.H1,
        "ts": TS,
        "open": Decimal("100"),
        "high": Decimal("110"),
        "low": Decimal("90"),
        "close": Decimal("105"),
        "volume": Decimal("12.5"),
    }
    data.update(overrides)
    return CandleSchema(**data)


@pytest.mark.parametrize("tf", list(Timeframe))
def test_vela_valida_en_cada_timeframe(tf: Timeframe) -> None:
    assert make(timeframe=tf).timeframe is tf


def test_ts_naive_rechazado() -> None:
    with pytest.raises(ValidationError, match="zona horaria"):
        make(ts=datetime(2024, 3, 5, 12, 0))


def test_ts_con_offset_se_normaliza_a_utc() -> None:
    ts = datetime(2024, 3, 5, 2, 0, tzinfo=timezone(timedelta(hours=2)))
    candle = make(ts=ts)
    assert candle.ts == TS
    assert candle.ts.utcoffset() == timedelta(0)


@pytest.mark.parametrize(
    ("tf", "ts"),
    [
        (Timeframe.M5, datetime(2024, 3, 5, 12, 3, tzinfo=UTC)),
        (Timeframe.M15, datetime(2024, 3, 5, 12, 10, tzinfo=UTC)),
        (Timeframe.H1, datetime(2024, 3, 5, 12, 15, tzinfo=UTC)),
        (Timeframe.H4, datetime(2024, 3, 5, 13, 0, tzinfo=UTC)),
        (Timeframe.D1, datetime(2024, 3, 5, 12, 0, tzinfo=UTC)),
        (Timeframe.M15, datetime(2024, 3, 5, 12, 0, 30, tzinfo=UTC)),
    ],
)
def test_ts_desalineado_rechazado(tf: Timeframe, ts: datetime) -> None:
    with pytest.raises(ValidationError, match="alineado"):
        make(timeframe=tf, ts=ts)


def test_high_menor_que_close() -> None:
    with pytest.raises(ValidationError, match="high"):
        make(high=Decimal("104"))


def test_low_mayor_que_open() -> None:
    with pytest.raises(ValidationError, match="low"):
        make(low=Decimal("101"))


@pytest.mark.parametrize("campo", ["open", "high", "low", "close"])
@pytest.mark.parametrize("valor", [Decimal("0"), Decimal("-1")])
def test_precios_no_positivos(campo: str, valor: Decimal) -> None:
    with pytest.raises(ValidationError, match="mayor que 0"):
        make(**{campo: valor})


def test_precio_no_finito() -> None:
    with pytest.raises(ValidationError):
        make(open=Decimal("NaN"))


def test_volumen_negativo() -> None:
    with pytest.raises(ValidationError, match="volumen"):
        make(volume=Decimal("-0.1"))


def test_volumen_cero_valido() -> None:
    assert make(volume=Decimal("0")).volume == 0


def test_decimales_se_serializan_como_cadena() -> None:
    dump = make(open=Decimal("100.10")).model_dump(mode="json")
    for campo in ("open", "high", "low", "close", "volume"):
        assert isinstance(dump[campo], str)
    assert dump["open"] == "100.10"
    assert dump["timeframe"] == "1h"


def test_inmutable() -> None:
    candle = make()
    with pytest.raises(ValidationError):
        candle.close = Decimal("1")  # type: ignore[misc]
