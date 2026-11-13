"""Proveedor provisional Yahoo y timeframe 5m: CHECK ampliados y datos de instrumentos

- `ck_instruments_provider` admite `YAHOO` (se conserva `OANDA`, D29).
- `ck_ohlcv_bars_timeframe` y `ck_trade_signals_timeframe` admiten `5m` (D36).
- EUR/USD, XAU/USD y NAS100 pasan a `YAHOO` con sus tickers (D29): `EURUSD=X`, `GC=F` y `^NDX`.
  Ojo: `GC=F` es el futuro continuo del oro, no el spot (`XAUUSD=X` no devuelve datos en Yahoo).

Downgrade: devuelve los 3 instrumentos a `OANDA` con sus símbolos originales y restaura los
CHECK anteriores. Como los datos obtenidos de Yahoo (GC=F es un futuro, 4h remuestreadas, etc.)
no son compatibles con OANDA, el downgrade los DESCARTA: borra TODAS las filas de `ohlcv_bars`
de EUR/USD, XAU/USD y NAS100 (cualquier timeframe), para que un `incremental` posterior desde
OANDA no mezcle fuentes. BTC/USDT (Binance) no se toca. Además, como `5m` dejaría de ser válido,
ANTES de restaurar el CHECK se borran las filas `5m` de `trade_signals` (limpieza explícita) y
las `5m` restantes de `ohlcv_bars` (BTC/USDT).

Revision ID: 0005_yahoo_5m
Revises: 0004_trade_signals
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_yahoo_5m"
down_revision: str | None = "0004_trade_signals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# symbol -> (provider_symbol OANDA, provider_symbol Yahoo)
_TICKERS = {
    "EUR/USD": ("EUR_USD", "EURUSD=X"),
    "XAU/USD": ("XAU_USD", "GC=F"),
    "NAS100": ("NAS100_USD", "^NDX"),
}

_PROVIDER_NEW = "provider IN ('BINANCE', 'OANDA', 'YAHOO')"
_PROVIDER_OLD = "provider IN ('BINANCE', 'OANDA')"
_TF_NEW = "timeframe IN ('5m', '15m', '1h', '4h', '1d')"
_TF_OLD = "timeframe IN ('15m', '1h', '4h', '1d')"


def _replace_check(table: str, name: str, expr: str) -> None:
    op.drop_constraint(name, table, type_="check")
    op.create_check_constraint(name, table, expr)


def _set_provider(provider: str, index: int) -> None:
    stmt = sa.text(
        "UPDATE instruments SET provider = :provider, provider_symbol = :psym WHERE symbol = :sym"
    )
    for symbol, tickers in _TICKERS.items():
        op.get_bind().execute(stmt, {"provider": provider, "psym": tickers[index], "sym": symbol})


def upgrade() -> None:
    _replace_check("instruments", "ck_instruments_provider", _PROVIDER_NEW)
    _replace_check("ohlcv_bars", "ck_ohlcv_bars_timeframe", _TF_NEW)
    _replace_check("trade_signals", "ck_trade_signals_timeframe", _TF_NEW)
    _set_provider("YAHOO", 1)


def downgrade() -> None:
    symbols = list(_TICKERS)
    op.get_bind().execute(
        sa.text(
            "DELETE FROM ohlcv_bars WHERE instrument_id IN "
            "(SELECT id FROM instruments WHERE symbol IN :symbols)"
        ).bindparams(sa.bindparam("symbols", expanding=True)),
        {"symbols": symbols},
    )
    _set_provider("OANDA", 0)
    op.execute("DELETE FROM ohlcv_bars WHERE timeframe = '5m'")
    op.execute("DELETE FROM trade_signals WHERE timeframe = '5m'")
    _replace_check("trade_signals", "ck_trade_signals_timeframe", _TF_OLD)
    _replace_check("ohlcv_bars", "ck_ohlcv_bars_timeframe", _TF_OLD)
    _replace_check("instruments", "ck_instruments_provider", _PROVIDER_OLD)
