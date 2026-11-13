"""trade_signals: tabla mínima con estado PENDING por defecto

Revision ID: 0004_trade_signals
Revises: 0003_ohlcv_bars
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004_trade_signals"
down_revision: str | None = "0003_ohlcv_bars"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trade_signals",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("instrument_id", sa.SmallInteger(), nullable=False),
        sa.Column("timeframe", sa.Text(), nullable=False),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("entry", sa.Numeric(24, 10), nullable=False),
        sa.Column("stop_loss", sa.Numeric(24, 10), nullable=False),
        sa.Column("take_profit", sa.Numeric(24, 10), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'PENDING'"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_trade_signals"),
        sa.ForeignKeyConstraint(
            ["instrument_id"], ["instruments.id"], name="fk_trade_signals_instrument_id"
        ),
        sa.CheckConstraint(
            "timeframe IN ('15m', '1h', '4h', '1d')", name="ck_trade_signals_timeframe"
        ),
        sa.CheckConstraint("direction IN ('LONG', 'SHORT')", name="ck_trade_signals_direction"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'REJECTED', 'EXECUTED')",
            name="ck_trade_signals_status",
        ),
    )
    op.create_index("ix_trade_signals_status_created_at", "trade_signals", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_trade_signals_status_created_at", table_name="trade_signals")
    op.drop_table("trade_signals")
