"""`default_since`: horizontes por proveedor (D17, D30). Sin base de datos."""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import Settings
from app.schemas.enums import Provider, Timeframe
from app.services.ingestion import default_since

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("tf", "days"),
    [
        (Timeframe.M5, 59),
        (Timeframe.M15, 59),
        (Timeframe.H1, 729),
        (Timeframe.H4, 729),
        (Timeframe.D1, 5 * 365),
    ],
)
def test_yahoo_usa_sus_horizontes(tf: Timeframe, days: int) -> None:
    assert default_since(tf, NOW, Settings(), Provider.YAHOO) == NOW - timedelta(days=days)


@pytest.mark.parametrize(
    ("tf", "days"),
    [
        (Timeframe.M5, 90),
        (Timeframe.M15, 365),
        (Timeframe.H1, 5 * 365),
        (Timeframe.H4, 5 * 365),
        (Timeframe.D1, 5 * 365),
    ],
)
def test_otros_proveedores_mantienen_d17(tf: Timeframe, days: int) -> None:
    for provider in (None, Provider.BINANCE, Provider.OANDA):
        assert default_since(tf, NOW, Settings(), provider) == NOW - timedelta(days=days)


def test_yahoo_respeta_la_configuracion() -> None:
    cfg = Settings(backfill_days_5m_yahoo=10, backfill_years_1d=2)
    assert default_since(Timeframe.M5, NOW, cfg, Provider.YAHOO) == NOW - timedelta(days=10)
    assert default_since(Timeframe.D1, NOW, cfg, Provider.YAHOO) == NOW - timedelta(days=730)
