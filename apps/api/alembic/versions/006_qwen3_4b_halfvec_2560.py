"""Switch the 005 embedding profile to qwen3-embedding 4B/halfvec(2560).

The 4B model exposed by the external legacy endpoint returns 2560 values.  A
PostgreSQL ``vector`` column cannot represent that typmod, so the migration
uses pgvector's ``halfvec(2560)`` while retaining exact cosine search as the
MVP baseline.  A downgrade is deliberately refused once vectors exist: a
2560-dimensional embedding cannot be losslessly converted to the old 1024
contract.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import HALFVEC, Vector

revision = "006"
down_revision = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_DIMENSIONS = 1024
NEW_DIMENSIONS = 2560


def _assert_no_vectors(table: str) -> None:
    bind = op.get_bind()
    count = bind.execute(
        sa.text(f"SELECT count(*) FROM {table} WHERE embedding IS NOT NULL")
    ).scalar_one()
    if count:
        raise RuntimeError(
            "EMBEDDING_REINDEX_REQUIRED_BEFORE_DIMENSION_MIGRATION"
        )


def _replace_dimension_checks(dimension: int) -> None:
    op.drop_constraint(
        "ck_corpus_chunks_embedding_dimensions", "corpus_chunks", type_="check"
    )
    op.drop_constraint(
        "ck_corpus_chunks_embedding_model", "corpus_chunks", type_="check"
    )
    op.drop_constraint(
        "ck_embedding_batches_dimensions", "embedding_batches", type_="check"
    )
    op.drop_constraint(
        "ck_semantic_search_runs_dimensions",
        "semantic_search_runs",
        type_="check",
    )
    op.drop_constraint(
        "ck_human_retrieval_evaluations_dimensions",
        "human_retrieval_evaluations",
        type_="check",
    )
    op.create_check_constraint(
        "ck_corpus_chunks_embedding_dimensions",
        "corpus_chunks",
        f"embedding_dimensions IS NULL OR embedding_dimensions = {dimension}",
    )
    op.create_check_constraint(
        "ck_corpus_chunks_embedding_model",
        "corpus_chunks",
        "embedding IS NULL OR (embedding_model IS NOT NULL AND "
        f"embedding_dimensions = {dimension})",
    )
    op.create_check_constraint(
        "ck_embedding_batches_dimensions",
        "embedding_batches",
        f"embedding_dimensions = {dimension}",
    )
    op.create_check_constraint(
        "ck_semantic_search_runs_dimensions",
        "semantic_search_runs",
        f"embedding_dimensions = {dimension}",
    )
    op.create_check_constraint(
        "ck_human_retrieval_evaluations_dimensions",
        "human_retrieval_evaluations",
        f"embedding_dimensions = {dimension}",
    )


def upgrade() -> None:
    _assert_no_vectors("corpus_chunks")
    op.alter_column(
        "corpus_chunks",
        "embedding",
        type_=HALFVEC(NEW_DIMENSIONS),
        existing_nullable=True,
        postgresql_using="embedding::halfvec",
    )
    _replace_dimension_checks(NEW_DIMENSIONS)


def downgrade() -> None:
    _assert_no_vectors("corpus_chunks")
    _replace_dimension_checks(OLD_DIMENSIONS)
    op.alter_column(
        "corpus_chunks",
        "embedding",
        type_=Vector(OLD_DIMENSIONS),
        existing_nullable=True,
        postgresql_using="embedding::vector",
    )
