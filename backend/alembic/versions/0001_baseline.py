"""baseline: verifica las extensiones requeridas

Las extensiones las crea `scripts/setup_db.sh` como superusuario (TimescaleDB no es
*trusted*, el rol de la aplicación no puede crearla). Esta migración solo comprueba
que existen y falla con un mensaje claro si falta alguna.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REQUIRED_EXTENSIONS = {"uuid-ossp", "timescaledb"}


def upgrade() -> None:
    installed = set(
        op.get_bind()
        .execute(
            sa.text("SELECT extname FROM pg_extension WHERE extname = ANY(:names)"),
            {"names": list(REQUIRED_EXTENSIONS)},
        )
        .scalars()
        .all()
    )
    missing = sorted(REQUIRED_EXTENSIONS - installed)
    if missing:
        raise RuntimeError(
            f"Faltan extensiones de PostgreSQL: {', '.join(missing)}. "
            "Ejecuta `sudo -u postgres bash < backend/scripts/setup_db.sh` antes de migrar."
        )


def downgrade() -> None:
    pass
