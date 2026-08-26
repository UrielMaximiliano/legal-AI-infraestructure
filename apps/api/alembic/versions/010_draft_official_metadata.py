"""Persist official number and issue date on finalized drafts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "010"
down_revision = "009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "document_drafts",
        sa.Column("official_number", sa.Integer(), nullable=True),
    )
    op.add_column(
        "document_drafts",
        sa.Column("issued_on", sa.Date(), nullable=True),
    )
    op.create_check_constraint(
        "ck_drafts_official_number_positive",
        "document_drafts",
        "official_number IS NULL OR official_number > 0",
    )
    op.create_check_constraint(
        "ck_drafts_official_metadata_complete",
        "document_drafts",
        "(official_number IS NULL AND issued_on IS NULL) OR "
        "(official_number IS NOT NULL AND issued_on IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_drafts_official_metadata_complete", "document_drafts", type_="check"
    )
    op.drop_constraint(
        "ck_drafts_official_number_positive", "document_drafts", type_="check"
    )
    op.drop_column("document_drafts", "issued_on")
    op.drop_column("document_drafts", "official_number")
