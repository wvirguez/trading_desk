import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.schemas.enums import AssetClass, Provider, SessionType
from app.schemas.instrument import InstrumentSchema

FIXTURES = Path(__file__).parent.parent / "fixtures"


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def make_instrument(
    symbol: str,
    provider: Provider,
    provider_symbol: str,
    asset_class: AssetClass,
    tick: str,
    lot: str,
    session: SessionType,
) -> InstrumentSchema:
    base, _, quote = symbol.partition("/")
    return InstrumentSchema(
        symbol=symbol,
        asset_class=asset_class,
        provider=provider,
        provider_symbol=provider_symbol,
        base_currency=base,
        quote_currency=quote or "USD",
        tick_size=Decimal(tick),
        lot_size=Decimal(lot),
        session=session,
    )


@pytest.fixture
def btc() -> InstrumentSchema:
    return make_instrument(
        "BTC/USDT",
        Provider.BINANCE,
        "BTC/USDT",
        AssetClass.CRYPTO,
        "0.01",
        "0.00001",
        SessionType.CRYPTO_24_7,
    )


@pytest.fixture
def eurusd() -> InstrumentSchema:
    return make_instrument(
        "EUR/USD", Provider.OANDA, "EUR_USD", AssetClass.FX, "0.00001", "1", SessionType.FX_24_5
    )


@pytest.fixture
def xauusd() -> InstrumentSchema:
    return make_instrument(
        "XAU/USD", Provider.OANDA, "XAU_USD", AssetClass.METAL, "0.001", "1", SessionType.FX_24_5
    )


@pytest.fixture
def nas100() -> InstrumentSchema:
    return make_instrument(
        "NAS100",
        Provider.OANDA,
        "NAS100_USD",
        AssetClass.INDEX,
        "0.1",
        "0.1",
        SessionType.INDEX_CFD,
    )
