"""instruments: tabla y seed de los 4 instrumentos del MVP

Los valores de tick y lote son provisionales (ver requirements.md, sección 6).

Revision ID: 0002_instruments
Revises: 0001_baseline
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_instruments"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEED = [
    ("BTC/USDT", "CRYPTO", "BINANCE", "BTC/USDT", "BTC", "USDT", "0.01", "0.00001", "CRYPTO_24_7"),
    ("EUR/USD", "FX", "OANDA", "EUR_USD", "EUR", "USD", "0.00001", "1", "FX_24_5"),
    ("XAU/USD", "METAL", "OANDA", "XAU_USD", "XAU", "USD", "0.001", "1", "FX_24_5"),
    ("NAS100", "INDEX", "OANDA", "NAS100_USD", "NAS100", "USD", "0.1", "0.1", "INDEX_CFD"),
]


def upgrade() -> None:
    op.create_table(
        "instruments",
        sa.Column("id", sa.SmallInteger(), sa.Identity(), primary_key=True),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("asset_class", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_symbol", sa.Text(), nullable=False),
        sa.Column("base_currency", sa.Text(), nullable=False),
        sa.Column("quote_currency", sa.Text(), nullable=False),
        sa.Column("tick_size", sa.Numeric(20, 10), nullable=False),
        sa.Column("lot_size", sa.Numeric(20, 10), nullable=False),
        sa.Column("session", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("symbol", name="uq_instruments_symbol"),
        sa.CheckConstraint(
            "asset_class IN ('CRYPTO', 'FX', 'METAL', 'INDEX')", name="ck_instruments_asset_class"
        ),
        sa.CheckConstraint("provider IN ('BINANCE', 'OANDA')", name="ck_instruments_provider"),
        sa.CheckConstraint(
            "session IN ('CRYPTO_24_7', 'FX_24_5', 'INDEX_CFD')", name="ck_instruments_session"
        ),
        sa.CheckConstraint("tick_size > 0", name="ck_instruments_tick_size_positivo"),
        sa.CheckConstraint("lot_size > 0", name="ck_instruments_lot_size_positivo"),
    )

    insert = sa.text(
        "INSERT INTO instruments (symbol, asset_class, provider, provider_symbol, "
        "base_currency, quote_currency, tick_size, lot_size, session) "
        "VALUES (:symbol, :asset_class, :provider, :provider_symbol, :base_currency, "
        ":quote_currency, :tick_size, :lot_size, :session) "
        "ON CONFLICT (symbol) DO NOTHING"
    )
    keys = (
        "symbol",
        "asset_class",
        "provider",
        "provider_symbol",
        "base_currency",
        "quote_currency",
        "tick_size",
        "lot_size",
        "session",
    )
    for row in SEED:
        op.get_bind().execute(insert, dict(zip(keys, row, strict=True)))


def downgrade() -> None:
    op.drop_table("instruments")
