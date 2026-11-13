from app.market_data.ccxt_adapter import CcxtAdapter
from app.market_data.oanda import OandaAdapter
from app.market_data.registry import adapter_for
from app.schemas.enums import Provider
from app.schemas.instrument import InstrumentSchema


def test_adapter_for_segun_proveedor(btc: InstrumentSchema, eurusd: InstrumentSchema) -> None:
    a = adapter_for(btc)
    b = adapter_for(eurusd)
    assert isinstance(a, CcxtAdapter) and a.provider is Provider.BINANCE
    assert isinstance(b, OandaAdapter) and b.provider is Provider.OANDA
