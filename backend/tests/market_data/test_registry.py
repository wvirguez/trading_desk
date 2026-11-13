from app.market_data.ccxt_adapter import CcxtAdapter
from app.market_data.oanda import OandaAdapter
from app.market_data.registry import adapter_for
from app.market_data.yahoo import YahooAdapter
from app.schemas.enums import AssetClass, Provider, SessionType
from app.schemas.instrument import InstrumentSchema
from tests.market_data.conftest import make_instrument


def test_adapter_for_segun_proveedor(btc: InstrumentSchema, eurusd: InstrumentSchema) -> None:
    a = adapter_for(btc)
    b = adapter_for(eurusd)
    assert isinstance(a, CcxtAdapter) and a.provider is Provider.BINANCE
    assert isinstance(b, OandaAdapter) and b.provider is Provider.OANDA


def test_adapter_for_yahoo() -> None:
    inst = make_instrument(
        "EUR/USD", Provider.YAHOO, "EURUSD=X", AssetClass.FX, "0.00001", "1", SessionType.FX_24_5
    )
    adapter = adapter_for(inst)
    assert isinstance(adapter, YahooAdapter) and adapter.provider is Provider.YAHOO
