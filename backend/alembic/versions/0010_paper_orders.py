"""paper_orders: órdenes del paper trading simulado (D133)

Revision ID: 0010_paper_orders
Revises: 0009_agent_analyses_unique_step
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0010_paper_orders"
down_revision: str | None = "0009_agent_analyses_unique_step"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATE_CHECK = (
    "(status = 'PENDING_FILL' AND fill_price IS NULL AND filled_at IS NULL "
    "AND exit_price IS NULL AND closed_at IS NULL AND realized_pnl IS NULL) "
    "OR (status = 'OPEN' AND fill_price IS NOT NULL AND filled_at IS NOT NULL "
    "AND exit_price IS NULL AND closed_at IS NULL AND realized_pnl IS NULL) "
    "OR (status IN ('CLOSED_TP', 'CLOSED_SL') AND fill_price IS NOT NULL "
    "AND filled_at IS NOT NULL AND exit_price IS NOT NULL AND closed_at IS NOT NULL "
    "AND realized_pnl IS NOT NULL)"
)


def upgrade() -> None:
    op.create_table(
        "paper_orders",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("signal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("instrument_id", sa.SmallInteger(), nullable=False),
        sa.Column("timeframe", sa.Text(), nullable=False),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("units", sa.Numeric(24, 10), nullable=False),
        sa.Column("signal_entry", sa.Numeric(24, 10), nullable=False),
        sa.Column("stop_loss", sa.Numeric(24, 10), nullable=False),
        sa.Column("take_profit", sa.Numeric(24, 10), nullable=False),
        sa.Column("risk_amount", sa.Numeric(24, 10), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'PENDING_FILL'"), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fill_price", sa.Numeric(24, 10)),
        sa.Column("exit_price", sa.Numeric(24, 10)),
        sa.Column("realized_pnl", sa.Numeric(24, 10)),
        sa.Column("filled_at", sa.DateTime(timezone=True)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("last_processed_ts", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_paper_orders"),
        sa.ForeignKeyConstraint(["signal_id"], ["trade_signals.id"], name="fk_paper_orders_signal"),
        sa.ForeignKeyConstraint(
            ["instrument_id"], ["instruments.id"], name="fk_paper_orders_instrument"
        ),
        sa.UniqueConstraint("signal_id", name="uq_paper_orders_signal_id"),
        sa.CheckConstraint(
            "timeframe IN ('5m', '15m', '1h', '4h', '1d')", name="ck_paper_orders_timeframe"
        ),
        sa.CheckConstraint("direction IN ('LONG', 'SHORT')", name="ck_paper_orders_direction"),
        sa.CheckConstraint(
            "status IN ('PENDING_FILL', 'OPEN', 'CLOSED_TP', 'CLOSED_SL')",
            name="ck_paper_orders_status",
        ),
        sa.CheckConstraint(STATE_CHECK, name="ck_paper_orders_status_state"),
    )
    op.create_index("ix_paper_orders_status", "paper_orders", ["status"])
    op.create_index("ix_paper_orders_closed_at", "paper_orders", ["closed_at"])


def downgrade() -> None:
    op.drop_index("ix_paper_orders_closed_at", table_name="paper_orders")
    op.drop_index("ix_paper_orders_status", table_name="paper_orders")
    op.drop_table("paper_orders")
