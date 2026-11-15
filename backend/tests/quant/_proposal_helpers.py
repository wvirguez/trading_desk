"""Constructores compartidos por los tests de la propuesta determinista."""

from datetime import UTC, datetime
from decimal import Decimal

from app.schemas.agents import MarketStructureReport, QuantAlphaReport, TimeframeStructure
from app.schemas.enums import (
    AssetClass,
    Bias,
    Direction,
    Playbook,
    Provider,
    RegimeLabel,
    SessionType,
    Timeframe,
)
from app.schemas.instrument import InstrumentSchema
from app.schemas.quant import FairValueGap, RegimeStats

D = Decimal
ZONE_TS = datetime(2026, 11, 1, 10, tzinfo=UTC)
DEFAULT_INVALIDATION = D("1.07000")


def _inst(
    symbol: str,
    ac: AssetClass,
    prov: Provider,
    base: str,
    quote: str,
    tick: str,
    lot: str,
    session: SessionType,
) -> InstrumentSchema:
    return InstrumentSchema(
        symbol=symbol,
        asset_class=ac,
        provider=prov,
        provider_symbol=symbol,
        base_currency=base,
        quote_currency=quote,
        tick_size=D(tick),
        lot_size=D(lot),
        session=session,
    )


# Tick y lote del seed (migración 0002).
SEED = {
    "BTC/USDT": _inst(
        "BTC/USDT",
        AssetClass.CRYPTO,
        Provider.BINANCE,
        "BTC",
        "USDT",
        "0.01",
        "0.00001",
        SessionType.CRYPTO_24_7,
    ),
    "EUR/USD": _inst(
        "EUR/USD", AssetClass.FX, Provider.YAHOO, "EUR", "USD", "0.00001", "1", SessionType.FX_24_5
    ),
    "XAU/USD": _inst(
        "XAU/USD",
        AssetClass.METAL,
        Provider.YAHOO,
        "XAU",
        "USD",
        "0.001",
        "1",
        SessionType.FX_24_5,
    ),
    "NAS100": _inst(
        "NAS100",
        AssetClass.INDEX,
        Provider.YAHOO,
        "NAS100",
        "USD",
        "0.1",
        "0.1",
        SessionType.INDEX_CFD,
    ),
}


def make_structure(
    symbol: str = "EUR/USD",
    bias: Bias = Bias.BULLISH,
    invalidation: Decimal | None = DEFAULT_INVALIDATION,
    zone_ts: datetime | None = ZONE_TS,
    timeframe: Timeframe = Timeframe.H1,
) -> MarketStructureReport:
    tfs = [
        TimeframeStructure(timeframe=tf, bias=bias, key_levels=[], open_fvg_ts=[], comment="x")
        for tf in (timeframe, Timeframe.D1)
    ]
    return MarketStructureReport(
        symbol=symbol,
        entry_timeframe=timeframe,
        timeframes=tfs,
        htf_alignment=bias,
        zone_ts=zone_ts,
        invalidation_level=invalidation,
        reasoning="x",
    )


def make_quant(
    symbol: str = "EUR/USD",
    playbook: Playbook = Playbook.TREND_FOLLOWING,
    zscore: float = 0.0,
    timeframe: Timeframe = Timeframe.H1,
) -> QuantAlphaReport:
    return QuantAlphaReport(
        symbol=symbol,
        timeframe=timeframe,
        regime=RegimeLabel.TRENDING,
        stats=RegimeStats(
            hurst=0.6, adf_pvalue=0.5, zscore=zscore, volatility_ratio=1.0, n_obs=500
        ),
        playbook=playbook,
        reasoning="x",
    )


def make_fvg(
    direction: Direction, low: str, high: str, mitigated: bool = False, ts: datetime = ZONE_TS
) -> FairValueGap:
    return FairValueGap(
        ts=ts,
        direction=direction,
        low=D(low),
        high=D(high),
        mitigated_at=datetime(2026, 11, 2, tzinfo=UTC) if mitigated else None,
    )
