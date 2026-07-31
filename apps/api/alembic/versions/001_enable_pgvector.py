"""Habilitar extensión pgvector.

Revision ID: 001
Revises:
Create Date: 2026-07-31
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Habilita la extensión vector (pgvector)."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    """No eliminar la extensión vector en downgrade (precaución)."""
    pass
