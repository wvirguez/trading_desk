"""ohlcv_bars: tabla, PK compuesta e hypertable de TimescaleDB (chunks de 30 días)

Revision ID: 0003_ohlcv_bars
Revises: 0002_instruments
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_ohlcv_bars"
down_revision: str | None = "0002_instruments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ohlcv_bars",
        sa.Column("instrument_id", sa.SmallInteger(), nullable=False),
        sa.Column("timeframe", sa.Text(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric(24, 10), nullable=False),
        sa.Column("high", sa.Numeric(24, 10), nullable=False),
        sa.Column("low", sa.Numeric(24, 10), nullable=False),
        sa.Column("close", sa.Numeric(24, 10), nullable=False),
        sa.Column("volume", sa.Numeric(30, 10), nullable=False),
        sa.Column(
            "ingested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("instrument_id", "timeframe", "ts", name="pk_ohlcv_bars"),
        sa.ForeignKeyConstraint(
            ["instrument_id"], ["instruments.id"], name="fk_ohlcv_bars_instrument_id"
        ),
        sa.CheckConstraint(
            "timeframe IN ('15m', '1h', '4h', '1d')", name="ck_ohlcv_bars_timeframe"
        ),
        sa.CheckConstraint(
            "high >= GREATEST(open, close, low) AND low <= LEAST(open, close) "
            "AND open > 0 AND high > 0 AND low > 0 AND close > 0 AND volume >= 0",
            name="ck_ohlcv_bars_ohlc",
        ),
    )
    op.execute(
        "SELECT create_hypertable('ohlcv_bars', 'ts', chunk_time_interval => INTERVAL '30 days')"
    )


def downgrade() -> None:
    op.drop_table("ohlcv_bars")
