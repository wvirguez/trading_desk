from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.schemas.enums import AssetClass, Direction, Provider, SessionType, SignalStatus, Timeframe


def test_valores_de_enums_segun_la_spec() -> None:
    assert {m.name: m.value for m in AssetClass} == {
        "CRYPTO": "CRYPTO", "FX": "FX", "METAL": "METAL", "INDEX": "INDEX",
    }  # fmt: skip
    assert {m.name: m.value for m in Provider} == {"BINANCE": "BINANCE", "OANDA": "OANDA"}
    assert {m.name: m.value for m in Timeframe} == {
        "M15": "15m", "H1": "1h", "H4": "4h", "D1": "1d",
    }  # fmt: skip
    assert [m.value for m in Direction] == ["LONG", "SHORT"]
    assert [m.value for m in SignalStatus] == ["PENDING", "APPROVED", "REJECTED", "EXECUTED"]
    assert [m.value for m in SessionType] == ["CRYPTO_24_7", "FX_24_5", "INDEX_CFD"]


@pytest.mark.parametrize(
    ("tf", "delta"),
    [
        (Timeframe.M15, timedelta(minutes=15)),
        (Timeframe.H1, timedelta(hours=1)),
        (Timeframe.H4, timedelta(hours=4)),
        (Timeframe.D1, timedelta(days=1)),
    ],
)
def test_duration(tf: Timeframe, delta: timedelta) -> None:
    assert tf.duration == delta


def test_floor() -> None:
    dt = datetime(2024, 3, 5, 14, 52, 31, tzinfo=UTC)
    assert Timeframe.M15.floor(dt) == datetime(2024, 3, 5, 14, 45, tzinfo=UTC)
    assert Timeframe.H1.floor(dt) == datetime(2024, 3, 5, 14, 0, tzinfo=UTC)
    assert Timeframe.H4.floor(dt) == datetime(2024, 3, 5, 12, 0, tzinfo=UTC)
    assert Timeframe.D1.floor(dt) == datetime(2024, 3, 5, 0, 0, tzinfo=UTC)


def test_floor_convierte_a_utc() -> None:
    dt = datetime(2024, 3, 5, 1, 30, tzinfo=timezone(timedelta(hours=2)))
    assert Timeframe.D1.floor(dt) == datetime(2024, 3, 4, tzinfo=UTC)


def test_floor_rechaza_naive() -> None:
    with pytest.raises(ValueError, match="zona horaria"):
        Timeframe.H1.floor(datetime(2024, 1, 1, 0, 0))
