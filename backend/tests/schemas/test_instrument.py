from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.enums import AssetClass, Provider, SessionType
from app.schemas.instrument import InstrumentSchema


def make(**overrides: Any) -> InstrumentSchema:
    data: dict[str, Any] = {
        "symbol": "BTC/USDT",
        "asset_class": AssetClass.CRYPTO,
        "provider": Provider.BINANCE,
        "provider_symbol": "BTC/USDT",
        "base_currency": "BTC",
        "quote_currency": "USDT",
        "tick_size": Decimal("0.01"),
        "lot_size": Decimal("0.00001"),
        "session": SessionType.CRYPTO_24_7,
    }
    data.update(overrides)
    return InstrumentSchema(**data)


def test_instrumento_valido_y_serializacion() -> None:
    dump = make().model_dump(mode="json")
    assert dump["tick_size"] == "0.01"
    assert dump["lot_size"] == "0.00001"


@pytest.mark.parametrize("campo", ["tick_size", "lot_size"])
@pytest.mark.parametrize("valor", [Decimal("0"), Decimal("-1")])
def test_tick_y_lote_deben_ser_positivos(campo: str, valor: Decimal) -> None:
    with pytest.raises(ValidationError, match="mayor que 0"):
        make(**{campo: valor})


def test_inmutable() -> None:
    with pytest.raises(ValidationError):
        make().symbol = "X"  # type: ignore[misc]
