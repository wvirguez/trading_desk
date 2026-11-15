"""trade_signals: columnas de trazabilidad y razonamiento de la Fase 3 (D96)

Revision ID: 0008_trade_signals_analysis
Revises: 0007_agent_analyses
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008_trade_signals_analysis"
down_revision: str | None = "0007_agent_analyses"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("trade_signals", sa.Column("analysis_id", postgresql.UUID(as_uuid=True)))
    op.add_column("trade_signals", sa.Column("rr", sa.Numeric(10, 4)))
    op.add_column("trade_signals", sa.Column("units", sa.Numeric(24, 10)))
    op.add_column("trade_signals", sa.Column("risk_amount", sa.Numeric(24, 10)))
    op.add_column("trade_signals", sa.Column("regime", sa.Text()))
    op.add_column("trade_signals", sa.Column("rationale", sa.Text()))
    op.add_column(
        "trade_signals",
        sa.Column(
            "veto_reasons",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_trade_signals_regime",
        "trade_signals",
        "regime IN ('MEAN_REVERTING', 'TRENDING', 'HIGH_VOLATILITY_NOISE')",
    )
    op.create_index("ix_trade_signals_analysis_id", "trade_signals", ["analysis_id"])


def downgrade() -> None:
    op.drop_index("ix_trade_signals_analysis_id", table_name="trade_signals")
    op.drop_constraint("ck_trade_signals_regime", "trade_signals", type_="check")
    for column in (
        "veto_reasons",
        "rationale",
        "regime",
        "risk_amount",
        "units",
        "rr",
        "analysis_id",
    ):
        op.drop_column("trade_signals", column)
