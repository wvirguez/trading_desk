"""Selección del adaptador según el proveedor del instrumento."""

import httpx

from app.core.config import Settings, get_settings
from app.market_data.base import MarketDataAdapter, MarketDataError
from app.market_data.ccxt_adapter import CcxtAdapter, build_binance_exchange
from app.market_data.oanda import OandaAdapter
from app.market_data.yahoo import YahooAdapter, yahoo_downloader
from app.schemas.enums import Provider
from app.schemas.instrument import InstrumentSchema

_OANDA_TIMEOUT_S = 30.0


def adapter_for(
    instrument: InstrumentSchema, settings: Settings | None = None
) -> MarketDataAdapter:
    """Crea un adaptador de un solo uso (cierra su conexión al terminar `fetch_ohlcv`)."""
    if instrument.provider is Provider.BINANCE:
        return CcxtAdapter(build_binance_exchange())
    if instrument.provider is Provider.OANDA:
        cfg = settings or get_settings()
        client = httpx.AsyncClient(timeout=_OANDA_TIMEOUT_S)
        return OandaAdapter(client, cfg, owns_client=True)
    if instrument.provider is Provider.YAHOO:
        return YahooAdapter(yahoo_downloader)
    raise MarketDataError(f"Proveedor sin adaptador: {instrument.provider}")
