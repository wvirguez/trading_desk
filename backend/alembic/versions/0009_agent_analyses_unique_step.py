"""agent_analyses: UNIQUE(analysis_id, step) (un paso solo se audita una vez por análisis)

Revision ID: 0009_agent_analyses_unique_step
Revises: 0008_trade_signals_analysis
Create Date: 2026-11-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009_agent_analyses_unique_step"
down_revision: str | None = "0008_trade_signals_analysis"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_agent_analyses_analysis_id_step", "agent_analyses", ["analysis_id", "step"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_agent_analyses_analysis_id_step", "agent_analyses", type_="unique")
