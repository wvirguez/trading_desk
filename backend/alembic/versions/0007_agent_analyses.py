"""agent_analyses: pasos de análisis multiagente, solo inserción (trigger, D88)

Revision ID: 0007_agent_analyses
Revises: 0006_strategies
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007_agent_analyses"
down_revision: str | None = "0006_strategies"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_analyses",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("analysis_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step", sa.Text(), nullable=False),
        sa.Column("instrument_id", sa.SmallInteger(), nullable=False),
        sa.Column("timeframe", sa.Text(), nullable=False),
        sa.Column("input", postgresql.JSONB(), nullable=False),
        sa.Column("output", postgresql.JSONB(), nullable=True),
        sa.Column("trace", postgresql.JSONB(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(18, 8), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        # clock_timestamp(): distinto por fila aunque varios pasos compartan transacción.
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.clock_timestamp(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_analyses"),
        sa.ForeignKeyConstraint(
            ["instrument_id"], ["instruments.id"], name="fk_agent_analyses_instrument_id"
        ),
        sa.CheckConstraint(
            "step IN ('STRUCTURE', 'QUANT', 'PROPOSAL', 'GUARDS', 'RISK_AUDIT')",
            name="ck_agent_analyses_step",
        ),
        sa.CheckConstraint(
            "timeframe IN ('5m', '15m', '1h', '4h', '1d')", name="ck_agent_analyses_timeframe"
        ),
        sa.CheckConstraint("status IN ('OK', 'ERROR')", name="ck_agent_analyses_status"),
    )
    op.create_index("ix_agent_analyses_analysis_id", "agent_analyses", ["analysis_id"])
    op.create_index(
        "ix_agent_analyses_instrument_id_created_at",
        "agent_analyses",
        ["instrument_id", sa.text("created_at DESC")],
    )
    op.execute(
        """
        CREATE FUNCTION agent_analyses_append_only() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'agent_analyses es de solo inserción';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agent_analyses_append_only
        BEFORE UPDATE OR DELETE ON agent_analyses
        FOR EACH ROW EXECUTE FUNCTION agent_analyses_append_only()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_agent_analyses_append_only ON agent_analyses")
    op.execute("DROP FUNCTION agent_analyses_append_only()")
    op.drop_index("ix_agent_analyses_instrument_id_created_at", table_name="agent_analyses")
    op.drop_index("ix_agent_analyses_analysis_id", table_name="agent_analyses")
    op.drop_table("agent_analyses")
