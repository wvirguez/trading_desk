"""strategies: un registro por backtest ejecutado (parámetros y métricas en JSONB)

Revision ID: 0006_strategies
Revises: 0005_yahoo_5m
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006_strategies"
down_revision: str | None = "0005_yahoo_5m"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "strategies",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("instrument_id", sa.SmallInteger(), nullable=False),
        sa.Column("timeframe", sa.Text(), nullable=False),
        sa.Column("params", postgresql.JSONB(), nullable=False),
        sa.Column("metrics", postgresql.JSONB(), nullable=False),
        sa.Column("config_hash", sa.Text(), nullable=False),
        sa.Column("data_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_strategies"),
        sa.ForeignKeyConstraint(
            ["instrument_id"], ["instruments.id"], name="fk_strategies_instrument_id"
        ),
        sa.CheckConstraint(
            "timeframe IN ('5m', '15m', '1h', '4h', '1d')", name="ck_strategies_timeframe"
        ),
    )
    op.create_index(
        "ix_strategies_instrument_id_created_at",
        "strategies",
        ["instrument_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_strategies_instrument_id_created_at", table_name="strategies")
    op.drop_table("strategies")
