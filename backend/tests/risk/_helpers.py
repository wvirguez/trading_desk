"""Utilidades compartidas por los tests de guardas."""

from decimal import Decimal

from app.core.config import Settings
from app.schemas.enums import AssetClass, Direction, Provider, SessionType
from app.schemas.instrument import InstrumentSchema
from app.schemas.risk import OpenPosition, PortfolioState, ProposedTrade

D = Decimal

EURUSD = InstrumentSchema(
    symbol="EUR/USD",
    asset_class=AssetClass.FX,
    provider=Provider.YAHOO,
    provider_symbol="EURUSD=X",
    base_currency="EUR",
    quote_currency="USD",
    tick_size=D("0.00001"),
    lot_size=D(1),
    session=SessionType.FX_24_5,
)


def make_settings() -> Settings:
    """Settings con valores explícitos, independientes del .env del usuario."""
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        risk_per_trade_pct=D("1.0"),
        max_daily_loss_pct=D("3.0"),
        min_rr=D("1.8"),
        max_open_risk_pct=D("3.0"),
        max_correlated_risk_pct=D("2.0"),
        correlation_window=100,
        correlation_threshold=D("0.7"),
    )


def make_state(
    positions: list[OpenPosition] | None = None,
    pnl: str = "0",
    equity: str = "10000",
    day_start: str = "10000",
) -> PortfolioState:
    return PortfolioState(
        equity=D(equity),
        day_start_equity=D(day_start),
        realized_pnl_today=D(pnl),
        open_positions=positions or [],
    )


def long_trade(tp: str = "1.08860", symbol: str = "EUR/USD") -> ProposedTrade:
    """Entrada 1.0850, stop 1.0830 (distancia 0.002); tp 1.0886 da R:R 1.8."""
    return ProposedTrade(
        symbol=symbol,
        direction=Direction.LONG,
        entry=D("1.08500"),
        stop_loss=D("1.08300"),
        take_profit=D(tp),
    )
