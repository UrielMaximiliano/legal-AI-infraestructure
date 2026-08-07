"""Live PostgreSQL migration and ORM/schema compatibility checks for 005."""

from __future__ import annotations

import asyncio
import copy
import os
import re
import subprocess
import uuid
from enum import Enum
from pathlib import Path

import pytest
from dotenv import dotenv_values
from sqlalchemy import Column, Integer, text, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.sql.elements import ClauseElement

from legal_ai.adapters.database.corpus_models import (
    CorpusChunkModel,
    CorpusDocumentModel,
)
from legal_ai.adapters.database.engine import create_engine
from legal_ai.adapters.database.ingestion_models import (
    EmbeddingBatchModel,
    IngestionFailureModel,
    IngestionRunModel,
)
from legal_ai.adapters.database.models import Base
from legal_ai.adapters.database.semantic_search_models import (
    HumanRetrievalEvaluationModel,
    SemanticSearchRunModel,
)
from legal_ai.embedding_contract import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL

NEW_TABLES = {
    "corpus_documents",
    "corpus_chunks",
    "ingestion_runs",
    "embedding_batches",
    "ingestion_failures",
    "semantic_search_runs",
    "human_retrieval_evaluations",
}
LEGACY_TABLES = {
    "employees",
    "case_files",
    "case_status_history",
    "document_templates",
    "designation_data",
    "document_drafts",
    "draft_transitions",
    "generation_attempts",
    "document_reviews",
    "review_comments",
    "review_events",
    "review_operation_requests",
    "document_exports",
    "export_attempts",
}
ORM_TABLES = {
    CorpusDocumentModel,
    CorpusChunkModel,
    IngestionRunModel,
    EmbeddingBatchModel,
    IngestionFailureModel,
    SemanticSearchRunModel,
    HumanRetrievalEvaluationModel,
}


def _run_alembic(*arguments: str) -> None:
    api_root = Path(__file__).resolve().parents[2]
    environment = dict(os.environ)
    for key, value in dotenv_values(api_root.parent.parent / ".env").items():
        if value is not None:
            environment.setdefault(key, value)
    environment.setdefault("POSTGRES_HOST", "localhost")
    environment.setdefault("POSTGRES_PORT", "5432")
    environment.setdefault("POSTGRES_DB", "legal_ai")
    environment.setdefault("POSTGRES_USER", "legal_ai")
    environment.setdefault("POSTGRES_PASSWORD", "test-password")
    subprocess.run(
        ["uv", "run", "alembic", *arguments],
        cwd=api_root,
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )


async def _tables() -> set[str]:
    engine = create_engine()
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            return set(result.scalars())
    finally:
        await engine.dispose()


async def _legacy_snapshot() -> dict[str, object]:
    engine = create_engine()
    try:
        async with engine.connect() as connection:
            columns = await connection.execute(
                text(
                    "SELECT table_name, column_name, data_type, udt_name, "
                    "is_nullable, column_default "
                    "FROM information_schema.columns "
                    "WHERE table_schema = 'public' "
                    "ORDER BY table_name, ordinal_position"
                )
            )
            column_snapshot = tuple(
                (
                    row[0],
                    row[1],
                    row[2],
                    row[3],
                    row[4],
                    row[5],
                )
                for row in columns
                if row[0] in LEGACY_TABLES
            )
            constraints = tuple(
                (
                    row[0],
                    row[1],
                    row[2],
                    row[3],
                )
                for row in await connection.execute(
                    text(
                        "SELECT c.relname, con.conname, con.contype, "
                        "pg_get_constraintdef(con.oid) "
                        "FROM pg_constraint con "
                        "JOIN pg_class c ON c.oid = con.conrelid "
                        "JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE n.nspname = 'public'"
                    )
                )
                if row[0] in LEGACY_TABLES
            )
            indexes = tuple(
                (row[0], row[1], row[2])
                for row in await connection.execute(
                    text(
                        "SELECT tablename, indexname, indexdef "
                        "FROM pg_indexes WHERE schemaname = 'public'"
                    )
                )
                if row[0] in LEGACY_TABLES
            )
            tables = await connection.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            existing_tables = set(tables.scalars())
            rows: dict[str, tuple[str, ...]] = {}
            for table in LEGACY_TABLES:
                rows[table] = (
                    tuple(
                        await connection.scalars(
                            text(
                                f"SELECT row_to_json(t)::text FROM "
                                f'(SELECT * FROM "{table}") AS t '
                                "ORDER BY row_to_json(t)::text"
                            )
                        )
                    )
                    if table in existing_tables
                    else ()
                )
            return {
                "columns": column_snapshot,
                "constraints": constraints,
                "indexes": indexes,
                "rows": rows,
            }
    finally:
        await engine.dispose()


async def _column_metadata(table: str) -> dict[str, tuple[str, str | None]]:
    engine = create_engine()
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT column_name, is_nullable, column_default "
                    "FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = :table"
                ),
                {"table": table},
            )
            return {row[0]: (row[1], row[2]) for row in result}
    finally:
        await engine.dispose()


def _normalize_catalog_sql(value: str | None) -> str | None:
    """Normalize whitespace only; PostgreSQL produced both compared definitions."""

    return " ".join(value.replace("public.", "").split()) if value is not None else None


def _normalize_sql_default(value: str) -> str:
    """Normalize PostgreSQL/SQLAlchemy default SQL without erasing semantics."""

    normalized = " ".join(value.replace("public.", "").split())
    normalized = re.sub(r"::(?:character varying|text)\b", "", normalized)
    while normalized.startswith("(") and normalized.endswith(")"):
        depth = 0
        balanced = True
        for index, character in enumerate(normalized):
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0 and index != len(normalized) - 1:
                    balanced = False
                    break
        if not balanced or depth != 0:
            break
        normalized = normalized[1:-1].strip()
    return normalized


def _normalize_default_contract(
    default: object, *, server: bool = False
) -> tuple[object, ...]:
    """Return a stable, typed representation of a client/server default."""

    argument = getattr(default, "arg", default)
    if argument is None:
        return ("none",)
    if isinstance(argument, Enum):
        enum_type = type(argument)
        return (
            "enum",
            f"{enum_type.__module__}.{enum_type.__qualname__}",
            argument.value,
        )
    if isinstance(argument, ClauseElement):
        compiled = str(argument.compile(dialect=postgresql.dialect()))
        return ("sql", _normalize_sql_default(compiled))
    if server and isinstance(argument, str):
        if argument in {"true", "false"} or re.fullmatch(r"-?\d+(?:\.\d+)?", argument):
            expression = argument
        else:
            expression = "'" + argument.replace("'", "''") + "'"
        return ("sql", _normalize_sql_default(expression))
    if isinstance(argument, bool):
        return ("scalar", "bool", argument)
    if isinstance(argument, int):
        return ("scalar", "int", argument)
    if isinstance(argument, float):
        return ("scalar", "float", argument)
    if isinstance(argument, str):
        return ("scalar", "str", argument)
    if callable(argument):
        module = getattr(argument, "__module__", "<unknown>")
        qualname = getattr(argument, "__qualname__", "<anonymous>")
        return ("callable", f"{module}.{qualname}")
    return ("value", type(argument).__name__, str(argument))


CLIENT_DEFAULT_CONTRACT: dict[str, dict[str, tuple[object, ...]]] = {
    "corpus_documents": {
        "id": ("callable", "uuid.uuid4"),
        "metadata": ("callable", "builtins.dict"),
        "provenance_type": ("scalar", "str", "AUTOMATED"),
        "review_status": ("scalar", "str", "PENDING_REVIEW"),
        "review_version": ("scalar", "int", 1),
        "ingestion_status": (
            "enum",
            "legal_ai.domain.corpus.CorpusIngestionStatus",
            "DISCOVERED",
        ),
        "embedding_status": ("scalar", "str", "PENDING"),
    },
    "corpus_chunks": {
        "id": ("callable", "uuid.uuid4"),
        "generation": ("scalar", "int", 1),
        "state": ("scalar", "str", "STAGED"),
        "metadata": ("callable", "builtins.dict"),
    },
    "ingestion_runs": {
        "id": ("callable", "uuid.uuid4"),
        "status": (
            "enum",
            "legal_ai.domain.ingestion.IngestionRunStatus",
            "PENDING",
        ),
        "configuration_snapshot": ("callable", "builtins.dict"),
        "counts": ("callable", "builtins.dict"),
        "resume_count": ("scalar", "int", 0),
    },
    "embedding_batches": {
        "id": ("callable", "uuid.uuid4"),
        "status": (
            "enum",
            "legal_ai.domain.ingestion.EmbeddingBatchStatus",
            "PENDING",
        ),
        "chunk_ids": ("callable", "builtins.list"),
        "attempt_count": ("scalar", "int", 0),
    },
    "ingestion_failures": {
        "id": ("callable", "uuid.uuid4"),
        "retryable": ("scalar", "bool", False),
    },
    "semantic_search_runs": {
        "id": ("callable", "uuid.uuid4"),
        "filters_sanitized": ("callable", "builtins.dict"),
    },
    "human_retrieval_evaluations": {"id": ("callable", "uuid.uuid4")},
}

SERVER_DEFAULT_CONTRACT: dict[str, dict[str, tuple[object, ...]]] = {
    "corpus_documents": {
        "id": ("sql", "gen_random_uuid()"),
        "metadata": ("sql", "'{}'::jsonb"),
        "provenance_type": ("sql", "'AUTOMATED'"),
        "review_status": ("sql", "'PENDING_REVIEW'"),
        "review_version": ("sql", "1"),
        "ingestion_status": ("sql", "'DISCOVERED'"),
        "embedding_status": ("sql", "'PENDING'"),
        "created_at": ("sql", "now()"),
        "updated_at": ("sql", "now()"),
    },
    "corpus_chunks": {
        "id": ("sql", "gen_random_uuid()"),
        "generation": ("sql", "1"),
        "state": ("sql", "'STAGED'"),
        "metadata": ("sql", "'{}'::jsonb"),
        "created_at": ("sql", "now()"),
        "updated_at": ("sql", "now()"),
    },
    "ingestion_runs": {
        "id": ("sql", "gen_random_uuid()"),
        "status": ("sql", "'PENDING'"),
        "configuration_snapshot": ("sql", "'{}'::jsonb"),
        "counts": ("sql", "'{}'::jsonb"),
        "started_at": ("sql", "now()"),
        "resume_count": ("sql", "0"),
    },
    "embedding_batches": {
        "id": ("sql", "gen_random_uuid()"),
        "status": ("sql", "'PENDING'"),
        "chunk_ids": ("sql", "'[]'::jsonb"),
        "attempt_count": ("sql", "0"),
    },
    "ingestion_failures": {
        "id": ("sql", "gen_random_uuid()"),
        "retryable": ("sql", "false"),
        "created_at": ("sql", "now()"),
    },
    "semantic_search_runs": {
        "id": ("sql", "gen_random_uuid()"),
        "filters_sanitized": ("sql", "'{}'::jsonb"),
        "created_at": ("sql", "now()"),
    },
    "human_retrieval_evaluations": {
        "id": ("sql", "gen_random_uuid()"),
        "created_at": ("sql", "now()"),
    },
}


def _assert_default_contract(
    model: type[object],
    database_defaults: dict[str, str | None],
    *,
    client_contract: dict[str, tuple[object, ...]] | None = None,
    server_contract: dict[str, tuple[object, ...]] | None = None,
    check_database: bool = True,
) -> None:
    table = model.__table__  # type: ignore[attr-defined]
    expected_client = client_contract or CLIENT_DEFAULT_CONTRACT.get(table.name, {})
    expected_server = server_contract or SERVER_DEFAULT_CONTRACT.get(table.name, {})
    for column in table.columns:
        actual_client = _normalize_default_contract(column.default)
        expected_client_value = expected_client.get(column.name, ("none",))
        assert actual_client == expected_client_value, (
            table.name,
            column.name,
            "client_default",
            actual_client,
            expected_client_value,
        )

        actual_server = _normalize_default_contract(column.server_default, server=True)
        expected_server_value = expected_server.get(column.name, ("none",))
        assert actual_server == expected_server_value, (
            table.name,
            column.name,
            "server_default",
            actual_server,
            expected_server_value,
        )
        if check_database:
            database_value = database_defaults.get(column.name)
            actual_database = (
                ("none",)
                if database_value is None
                else ("sql", _normalize_sql_default(database_value))
            )
            assert actual_database == expected_server_value, (
                table.name,
                column.name,
                "postgres_default",
                actual_database,
                expected_server_value,
            )


def _assert_single_client_default(
    column: Column[object], expected: tuple[object, ...]
) -> None:
    assert _normalize_default_contract(column.default) == expected


async def _database_schema_definition(
    connection: object, schema: str, table: str
) -> dict[str, tuple[object, ...]]:
    execute = connection.execute  # type: ignore[attr-defined]
    parameters = {"schema": schema, "table": table}
    columns = await execute(
        text(
            "SELECT a.attname, format_type(a.atttypid, a.atttypmod), "
            "a.attnotnull, EXISTS (SELECT 1 FROM pg_constraint pk "
            "WHERE pk.conrelid = c.oid AND pk.contype = 'p' "
            "AND a.attnum = ANY(pk.conkey)), pg_get_expr(d.adbin, d.adrelid) "
            "FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "LEFT JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum "
            "WHERE n.nspname = :schema AND c.relname = :table "
            "AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum"
        ),
        parameters,
    )
    constraints = await execute(
        text(
            "SELECT con.conname, con.contype, pg_get_constraintdef(con.oid, true) "
            "FROM pg_constraint con JOIN pg_class c ON c.oid = con.conrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = :schema AND c.relname = :table "
            "AND con.contype <> 't' "
            "ORDER BY con.conname"
        ),
        parameters,
    )
    indexes = await execute(
        text(
            "SELECT ic.relname, i.indisunique, am.amname, "
            "ARRAY(SELECT pg_get_indexdef(i.indexrelid, key_position, true) "
            "FROM generate_series(1, i.indnkeyatts) key_position "
            "ORDER BY key_position), pg_get_expr(i.indpred, i.indrelid) "
            "FROM pg_index i JOIN pg_class c ON c.oid = i.indrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "JOIN pg_class ic ON ic.oid = i.indexrelid "
            "JOIN pg_am am ON am.oid = ic.relam "
            "WHERE n.nspname = :schema AND c.relname = :table "
            "AND NOT EXISTS (SELECT 1 FROM pg_constraint con "
            "WHERE con.conindid = i.indexrelid) ORDER BY ic.relname"
        ),
        parameters,
    )
    return {
        "columns": tuple(
            (row[0], row[1], row[2], row[3], _normalize_catalog_sql(row[4]))
            for row in columns
        ),
        "constraints": tuple(
            (row[0], row[1], _normalize_catalog_sql(row[2])) for row in constraints
        ),
        "indexes": tuple(
            (
                row[0],
                row[1],
                row[2],
                tuple(row[3]),
                _normalize_catalog_sql(row[4]),
            )
            for row in indexes
        ),
    }


async def _database_defaults(
    connection: object, schema: str, table: str
) -> dict[str, str | None]:
    execute = connection.execute  # type: ignore[attr-defined]
    result = await execute(
        text(
            "SELECT a.attname, pg_get_expr(d.adbin, d.adrelid) "
            "FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "LEFT JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum "
            "WHERE n.nspname = :schema AND c.relname = :table "
            "AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum"
        ),
        {"schema": schema, "table": table},
    )
    return {row[0]: row[1] for row in result}


def test_default_normalizer_is_typed_and_address_free() -> None:
    assert _normalize_default_contract(None) == ("none",)
    assert _normalize_default_contract(True) == ("scalar", "bool", True)
    assert _normalize_default_contract(1) == ("scalar", "int", 1)
    assert _normalize_default_contract(1.5) == ("scalar", "float", 1.5)
    assert _normalize_default_contract("value") == ("scalar", "str", "value")
    assert _normalize_default_contract(dict) == ("callable", "builtins.dict")
    assert _normalize_default_contract(text("now()")) == ("sql", "now()")
    assert "0x" not in repr(_normalize_default_contract(dict))


def test_default_comparator_rejects_artificial_client_default_mismatch() -> None:
    probe = Column("probe", Integer, default=2)
    with pytest.raises(AssertionError):
        _assert_single_client_default(probe, ("scalar", "int", 1))


def test_default_comparator_distinguishes_client_and_server_contracts() -> None:
    model = CorpusDocumentModel
    client_contract = copy.deepcopy(CLIENT_DEFAULT_CONTRACT["corpus_documents"])
    server_contract = copy.deepcopy(SERVER_DEFAULT_CONTRACT["corpus_documents"])

    # A correct client default does not compensate for an incorrect server default.
    with pytest.raises(AssertionError):
        incorrect_server = copy.deepcopy(server_contract)
        incorrect_server["review_version"] = ("sql", "2")
        _assert_default_contract(
            model,
            {},
            client_contract=client_contract,
            server_contract=incorrect_server,
            check_database=False,
        )

    # A correct server default does not compensate for an incorrect client default.
    with pytest.raises(AssertionError):
        incorrect_client = copy.deepcopy(client_contract)
        incorrect_client["review_version"] = ("scalar", "int", 2)
        _assert_default_contract(
            model,
            {},
            client_contract=incorrect_client,
            server_contract=server_contract,
            check_database=False,
        )

    # An expected absent client default is also contractual.
    with pytest.raises(AssertionError):
        absent_client = copy.deepcopy(client_contract)
        absent_client["title"] = ("scalar", "str", "unexpected")
        _assert_default_contract(
            model,
            {},
            client_contract=absent_client,
            server_contract=server_contract,
            check_database=False,
        )


async def _insert_legacy_fixture() -> uuid.UUID:
    fixture_id = uuid.uuid4()
    suffix = fixture_id.hex[:16]
    engine = create_engine()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO employees "
                    "(id, employee_number, first_name, last_name, document_type, "
                    "document_number, active) VALUES "
                    "(:id, :employee_number, 'Round', 'Trip', 'DNI', "
                    ":document_number, true)"
                ),
                {
                    "id": fixture_id,
                    "employee_number": f"005-roundtrip-{suffix}",
                    "document_number": f"005-{suffix}",
                },
            )
    finally:
        await engine.dispose()
    return fixture_id


async def _delete_legacy_fixture(fixture_id: uuid.UUID) -> None:
    engine = create_engine()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM employees WHERE id = :id"),
                {"id": fixture_id},
            )
    finally:
        await engine.dispose()


def _document_values(
    document_id: uuid.UUID, *, active_generation: int | None
) -> dict[str, object]:
    suffix = document_id.hex[:16]
    return {
        "id": document_id,
        "external_id": f"005-document-{suffix}",
        "document_type": "decreto",
        "document_subtype": "designacion_transitoria",
        "jurisdiction": "nacion",
        "language": "es",
        "source_name": "fixture-005",
        "source_identifier": f"fixture-005/{suffix}.txt",
        "raw_content": "contenido jurídico original",
        "raw_content_hash": "a" * 64,
        "normalized_content": "Contenido jurídico normalizado",
        "normalized_content_hash": "b" * 64,
        "metadata": {},
        "provenance_type": "AUTOMATED",
        "review_status": "PENDING_REVIEW",
        "review_version": 1,
        "ingestion_status": "COMPLETED",
        "embedding_status": "PENDING",
        "created_by_pipeline_version": "005-test",
        "normalization_version": "v1",
        "chunking_version": "v1",
        "active_generation": active_generation,
    }


def _chunk_values(
    document_id: uuid.UUID,
    chunk_id: uuid.UUID,
    *,
    generation: int,
    state: str,
    section_index: int,
    content_hash: str,
    embedding: list[float] | None = None,
) -> dict[str, object]:
    return {
        "id": chunk_id,
        "document_id": document_id,
        "generation": generation,
        "state": state,
        "section_type": "article",
        "section_index": section_index,
        "paragraph_index": 0,
        "content": f"chunk-{section_index}",
        "content_hash": content_hash,
        "token_count": 1,
        "embedding": embedding,
        "embedding_model": EMBEDDING_MODEL if embedding is not None else None,
        "embedding_dimensions": (
            EMBEDDING_DIMENSIONS if embedding is not None else None
        ),
        "normalization_version": "v1",
        "chunking_version": "v1",
        "metadata": {},
    }


@pytest.mark.integration
async def test_005_upgrade_has_contractual_schema_and_orm_mapping() -> None:
    _run_alembic("downgrade", "004")
    _run_alembic("upgrade", "head")
    try:
        assert await _tables() >= NEW_TABLES
        document_columns = await _column_metadata("corpus_documents")
        assert document_columns["external_id"][0] == "NO"
        assert document_columns["document_subtype"][0] == "NO"
        assert document_columns["review_version"] == ("NO", "1")
        chunk_columns = await _column_metadata("corpus_chunks")
        assert chunk_columns["paragraph_index"][0] == "YES"
        search_columns = await _column_metadata("semantic_search_runs")
        assert search_columns["minimum_score"][0] == "YES"
        assert search_columns["request_id"][0] == "NO"
        run_status = (await _column_metadata("ingestion_runs"))["status"]
        assert run_status[0] == "NO" and "PENDING" in (run_status[1] or "")
        run_columns = await _column_metadata("ingestion_runs")
        assert run_columns["resumed_at"][0] == "YES"
        assert run_columns["resume_count"] == ("NO", "0")
        assert run_columns["error_code"][0] == "YES"

        engine = create_engine()
        try:
            async with engine.connect() as connection:
                checks = set(
                    (
                        await connection.execute(
                            text(
                                "SELECT conname FROM pg_constraint "
                                "WHERE conname LIKE 'ck_corpus_%' "
                                "OR conname LIKE 'ck_embedding_batches_%' "
                                "OR conname LIKE 'ck_ingestion_runs_%' "
                                "OR conname LIKE 'ck_semantic_search_runs_%'"
                            )
                        )
                    ).scalars()
                )
                assert {
                    "ck_corpus_documents_ingestion_status",
                    "ck_corpus_documents_review_metadata",
                    "ck_corpus_documents_review_provenance",
                    "ck_corpus_documents_rejection_reason",
                    "ck_corpus_chunks_content_not_empty",
                    "ck_corpus_chunks_content_hash",
                    "ck_corpus_chunks_indexes_nonnegative",
                    "ck_embedding_batches_status",
                    "ck_ingestion_runs_resume_count",
                    "ck_ingestion_runs_finished_at",
                    "ck_ingestion_runs_error_code",
                    "ck_semantic_search_runs_filters_allowlist",
                    "ck_semantic_search_runs_request_id",
                    "ck_semantic_search_runs_error_code",
                } <= checks
                indexes = set(
                    (
                        await connection.execute(
                            text(
                                "SELECT indexname FROM pg_indexes "
                                "WHERE schemaname = 'public'"
                            )
                        )
                    ).scalars()
                )
                assert {
                    "ix_corpus_documents_search_filters",
                    "ix_semantic_search_runs_request",
                    "ix_semantic_search_runs_model_dimensions",
                    "uq_corpus_chunks_document_generation_hash",
                } <= indexes
                vector_type = await connection.scalar(
                    text(
                        "SELECT format_type(a.atttypid, a.atttypmod) "
                        "FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
                        "WHERE c.relname = 'corpus_chunks' AND a.attname = 'embedding'"
                    )
                )
                assert vector_type == "halfvec(2560)"
                trigger_names = set(
                    (
                        await connection.execute(
                            text(
                                "SELECT tgname FROM pg_trigger "
                                "WHERE tgrelid IN "
                                "('corpus_documents'::regclass, "
                                "'corpus_chunks'::regclass) "
                                "AND NOT tgisinternal"
                            )
                        )
                    ).scalars()
                )
                assert {
                    "trg_corpus_documents_active_generation_005",
                    "trg_corpus_chunks_active_generation_005",
                } <= trigger_names
                assert (
                    await connection.scalar(
                        text(
                            "SELECT 1 FROM pg_proc "
                            "WHERE proname = 'validate_corpus_active_generation_005'"
                        )
                    )
                    == 1
                )
                assert (
                    await connection.scalar(
                        text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
                    )
                    == 1
                )
        finally:
            await engine.dispose()

        comparison_schema = f"orm_005_{uuid.uuid4().hex}"
        engine = create_engine()
        try:
            async with engine.begin() as connection:
                await connection.execute(text(f'CREATE SCHEMA "{comparison_schema}"'))
                await connection.execute(
                    text(f'SET LOCAL search_path TO "{comparison_schema}", public')
                )
                orm_tables = [
                    table
                    for table in Base.metadata.sorted_tables
                    if table.name in NEW_TABLES
                ]
                await connection.run_sync(
                    lambda sync_connection: Base.metadata.create_all(
                        sync_connection, tables=orm_tables, checkfirst=False
                    )
                )

                for model in ORM_TABLES:
                    _assert_default_contract(
                        model,
                        await _database_defaults(
                            connection, "public", model.__tablename__
                        ),
                    )

                # Both sides are introspected after PostgreSQL has normalized SQL.
                # Constraint-backed PK/unique indexes are excluded by the catalog
                # query because their complete definitions are compared as
                # constraints. PostgreSQL constraint triggers are excluded from
                # ORM equivalence because SQLAlchemy metadata has no equivalent;
                # their definitions and behavior are tested separately below and
                # in the generation-swap tests. No other difference is allowlisted.
                for model in ORM_TABLES:
                    table_name = model.__tablename__
                    migrated = await _database_schema_definition(
                        connection, "public", table_name
                    )
                    mapped = await _database_schema_definition(
                        connection, comparison_schema, table_name
                    )
                    assert mapped == migrated, table_name

                await connection.execute(
                    text(f'DROP SCHEMA "{comparison_schema}" CASCADE')
                )
        finally:
            await engine.dispose()
    finally:
        _run_alembic("upgrade", "head")


@pytest.mark.integration
async def test_005_partial_unique_indexes_enforce_only_live_identities() -> None:
    _run_alembic("upgrade", "head")
    engine = create_engine()
    documents = CorpusDocumentModel.__table__
    chunks = CorpusChunkModel.__table__
    try:
        async with engine.begin() as connection:
            source_id = uuid.uuid4()
            source_live = _document_values(source_id, active_generation=None)
            source_live.update(
                source_name="partial-source",
                external_id="shared-external",
                source_identifier="partial/source-live.txt",
                raw_content_hash="1" * 64,
                normalized_content_hash="2" * 64,
            )
            await connection.execute(documents.insert().values(**source_live))

            source_collision = _document_values(uuid.uuid4(), active_generation=None)
            source_collision.update(
                source_name="partial-source",
                external_id="shared-external",
                source_identifier="partial/source-collision.txt",
                raw_content_hash="3" * 64,
                normalized_content_hash="4" * 64,
            )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        documents.insert().values(**source_collision)
                    )

            failed_documents: list[dict[str, object]] = []
            for number in range(2):
                failed = _document_values(uuid.uuid4(), active_generation=None)
                failed.update(
                    source_name="partial-source",
                    external_id="shared-external",
                    source_identifier=f"partial/source-failed-{number}.txt",
                    raw_content_hash=f"{number + 5:x}" * 64,
                    normalized_content_hash=f"{number + 7:x}" * 64,
                    ingestion_status="FAILED",
                )
                await connection.execute(documents.insert().values(**failed))
                failed_documents.append(failed)

            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        update(documents)
                        .where(documents.c.id == failed_documents[0]["id"])
                        .values(ingestion_status="COMPLETED")
                    )
            await connection.execute(
                update(documents)
                .where(documents.c.id == source_id)
                .values(ingestion_status="FAILED")
            )
            await connection.execute(
                update(documents)
                .where(documents.c.id == failed_documents[0]["id"])
                .values(ingestion_status="COMPLETED")
            )

            active_id = uuid.uuid4()
            active = _document_values(active_id, active_generation=1)
            active.update(
                source_name="identity-active",
                external_id="active",
                source_identifier="partial/shared-identity.txt",
                raw_content_hash="a" * 64,
                normalized_content_hash="b" * 64,
            )
            await connection.execute(documents.insert().values(**active))
            await connection.execute(
                chunks.insert().values(
                    **_chunk_values(
                        active_id,
                        uuid.uuid4(),
                        generation=1,
                        state="ACTIVE",
                        section_index=0,
                        content_hash="c" * 64,
                        embedding=[0.0] * 2560,
                    )
                )
            )

            inactive_documents: list[dict[str, object]] = []
            for number in range(2):
                inactive = _document_values(uuid.uuid4(), active_generation=None)
                inactive.update(
                    source_name="identity-inactive",
                    external_id=f"inactive-{number}",
                    source_identifier="partial/shared-identity.txt",
                    raw_content_hash="a" * 64,
                    normalized_content_hash="b" * 64,
                )
                await connection.execute(documents.insert().values(**inactive))
                inactive_documents.append(inactive)

            active_collision = _document_values(uuid.uuid4(), active_generation=1)
            active_collision.update(
                source_name="identity-active",
                external_id="active-collision",
                source_identifier="partial/shared-identity.txt",
                raw_content_hash="a" * 64,
                normalized_content_hash="b" * 64,
            )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        documents.insert().values(**active_collision)
                    )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        update(documents)
                        .where(documents.c.id == inactive_documents[0]["id"])
                        .values(active_generation=1)
                    )

            await connection.execute(
                update(documents)
                .where(documents.c.id == active_id)
                .values(active_generation=None)
            )
            await connection.execute(
                update(chunks)
                .where(chunks.c.document_id == active_id)
                .values(state="SUPERSEDED")
            )
            promoted_id = inactive_documents[0]["id"]
            await connection.execute(
                chunks.insert().values(
                    **_chunk_values(
                        promoted_id,
                        uuid.uuid4(),
                        generation=1,
                        state="ACTIVE",
                        section_index=0,
                        content_hash="d" * 64,
                        embedding=[0.0] * 2560,
                    )
                )
            )
            await connection.execute(
                update(documents)
                .where(documents.c.id == promoted_id)
                .values(active_generation=1)
            )

            predicates = dict(
                tuple(
                    await connection.execute(
                        text(
                            "SELECT ic.relname, pg_get_expr(i.indpred, i.indrelid) "
                            "FROM pg_index i JOIN pg_class ic ON ic.oid = i.indexrelid "
                            "WHERE ic.relname IN ("
                            "'uq_corpus_documents_source_external', "
                            "'uq_corpus_documents_identity_active')"
                        )
                    )
                )
            )
            assert (
                _normalize_catalog_sql(
                    predicates["uq_corpus_documents_source_external"]
                )
                == "((ingestion_status)::text <> 'FAILED'::text)"
            )
            assert _normalize_catalog_sql(
                predicates["uq_corpus_documents_identity_active"]
            ) == (
                "((active_generation IS NOT NULL) AND "
                "((ingestion_status)::text <> 'FAILED'::text))"
            )
    finally:
        cleanup_engine = create_engine()
        try:
            async with cleanup_engine.begin() as connection:
                await connection.execute(
                    documents.delete().where(
                        documents.c.source_name.in_(
                            ("partial-source", "identity-active", "identity-inactive")
                        )
                    )
                )
        finally:
            await cleanup_engine.dispose()
        await engine.dispose()


@pytest.mark.integration
async def test_005_round_trip_preserves_001_to_004_and_pgvector() -> None:
    _run_alembic("downgrade", "004")
    try:
        fixture_id = await _insert_legacy_fixture()
        before = await _legacy_snapshot()
        _run_alembic("upgrade", "head")
        after_upgrade = await _legacy_snapshot()
        assert after_upgrade == before

        _run_alembic("downgrade", "004")
        assert NEW_TABLES.isdisjoint(await _tables())
        assert await _legacy_snapshot() == before
        engine = create_engine()
        try:
            async with engine.connect() as connection:
                assert (
                    await connection.scalar(
                        text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
                    )
                    == 1
                )
                assert (
                    await connection.scalar(
                        text("SELECT version_num FROM alembic_version")
                    )
                    == "004"
                )
                assert not await connection.scalar(
                    text(
                        "SELECT 1 FROM pg_proc "
                        "WHERE proname = 'validate_corpus_active_generation_005'"
                    )
                )
                assert not await connection.scalar(
                    text(
                        "SELECT 1 FROM pg_trigger "
                        "WHERE tgname IN "
                        "('trg_corpus_documents_active_generation_005', "
                        "'trg_corpus_chunks_active_generation_005')"
                    )
                )
                assert not await connection.scalar(
                    text(
                        "SELECT 1 FROM pg_indexes "
                        "WHERE indexname IN ("
                        "'ix_corpus_documents_review_status', "
                        "'ix_corpus_documents_search_filters', "
                        "'ix_corpus_documents_source_identifier', "
                        "'ix_corpus_documents_hashes', "
                        "'ix_corpus_chunks_document_generation', "
                        "'ix_corpus_chunks_state', "
                        "'ix_ingestion_runs_status', "
                        "'ix_ingestion_failures_run', "
                        "'ix_semantic_search_runs_created', "
                        "'ix_semantic_search_runs_status', "
                        "'ix_semantic_search_runs_request', "
                        "'ix_semantic_search_runs_model_dimensions', "
                        "'ix_semantic_search_runs_error_code', "
                        "'ix_human_retrieval_evaluations_run', "
                        "'uq_corpus_documents_source_external', "
                        "'uq_corpus_documents_identity_active', "
                        "'uq_corpus_chunks_document_generation_position', "
                        "'uq_corpus_chunks_document_generation_hash'"
                        ")"
                    )
                )
        finally:
            await engine.dispose()

        _run_alembic("upgrade", "head")
        assert await _tables() >= NEW_TABLES
    finally:
        _run_alembic("upgrade", "head")
        if "fixture_id" in locals():
            await _delete_legacy_fixture(fixture_id)


@pytest.mark.integration
async def test_005_generation_constraints_allow_atomic_swap_and_rollback() -> None:
    _run_alembic("upgrade", "head")
    document_id = uuid.uuid4()
    first_chunk_id = uuid.uuid4()
    second_chunk_id = uuid.uuid4()
    engine = create_engine()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                CorpusDocumentModel.__table__.insert().values(
                    **_document_values(document_id, active_generation=None)
                )
            )
            await connection.execute(
                CorpusChunkModel.__table__.insert().values(
                    **_chunk_values(
                        document_id,
                        first_chunk_id,
                        generation=1,
                        state="ACTIVE",
                        section_index=0,
                        content_hash="c" * 64,
                        embedding=[0.0] * 2560,
                    )
                )
            )
            await connection.execute(
                update(CorpusDocumentModel.__table__)
                .where(CorpusDocumentModel.id == document_id)
                .values(active_generation=1)
            )

        with pytest.raises(DBAPIError):
            async with engine.begin() as connection:
                await connection.execute(
                    update(CorpusDocumentModel.__table__)
                    .where(CorpusDocumentModel.id == document_id)
                    .values(active_generation=99)
                )

        with pytest.raises(DBAPIError):
            async with engine.begin() as connection:
                await connection.execute(
                    CorpusChunkModel.__table__.insert().values(
                        **_chunk_values(
                            document_id,
                            second_chunk_id,
                            generation=2,
                            state="ACTIVE",
                            section_index=1,
                            content_hash="d" * 64,
                            embedding=[0.0] * 2560,
                        )
                    )
                )

        async with engine.begin() as connection:
            await connection.execute(
                update(CorpusChunkModel.__table__)
                .where(CorpusChunkModel.id == first_chunk_id)
                .values(state="SUPERSEDED")
            )
            await connection.execute(
                CorpusChunkModel.__table__.insert().values(
                    **_chunk_values(
                        document_id,
                        second_chunk_id,
                        generation=2,
                        state="ACTIVE",
                        section_index=1,
                        content_hash="d" * 64,
                        embedding=[0.0] * 2560,
                    )
                )
            )
            await connection.execute(
                update(CorpusDocumentModel.__table__)
                .where(CorpusDocumentModel.id == document_id)
                .values(active_generation=2)
            )

        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text(
                        "SELECT active_generation FROM corpus_documents WHERE id = :id"
                    ),
                    {"id": document_id},
                )
                == 2
            )
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM corpus_chunks "
                        "WHERE document_id = :id AND state = 'ACTIVE' "
                        "AND generation = 2"
                    ),
                    {"id": document_id},
                )
                == 1
            )
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM corpus_documents WHERE id = :id"),
                {"id": document_id},
            )
        await engine.dispose()


@pytest.mark.integration
async def test_005_generation_trigger_validates_old_and_new_on_reparent() -> None:
    _run_alembic("upgrade", "head")
    old_document_id = uuid.uuid4()
    new_document_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    engine = create_engine()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                CorpusDocumentModel.__table__.insert(),
                [
                    _document_values(old_document_id, active_generation=None),
                    _document_values(new_document_id, active_generation=None),
                ],
            )
            await connection.execute(
                CorpusChunkModel.__table__.insert().values(
                    **_chunk_values(
                        old_document_id,
                        chunk_id,
                        generation=1,
                        state="ACTIVE",
                        section_index=0,
                        content_hash="e" * 64,
                        embedding=[0.0] * 2560,
                    )
                )
            )
            await connection.execute(
                update(CorpusDocumentModel.__table__)
                .where(CorpusDocumentModel.id == old_document_id)
                .values(active_generation=1)
            )

        with pytest.raises(DBAPIError):
            async with engine.begin() as connection:
                await connection.execute(
                    update(CorpusChunkModel.__table__)
                    .where(CorpusChunkModel.id == chunk_id)
                    .values(document_id=new_document_id)
                )
                await connection.execute(
                    update(CorpusDocumentModel.__table__)
                    .where(CorpusDocumentModel.id == new_document_id)
                    .values(active_generation=1)
                )

        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text("SELECT document_id FROM corpus_chunks WHERE id = :id"),
                    {"id": chunk_id},
                )
                == old_document_id
            )
            assert (
                await connection.scalar(
                    text(
                        "SELECT active_generation FROM corpus_documents WHERE id = :id"
                    ),
                    {"id": old_document_id},
                )
                == 1
            )
            assert (
                await connection.scalar(
                    text(
                        "SELECT active_generation FROM corpus_documents WHERE id = :id"
                    ),
                    {"id": new_document_id},
                )
                is None
            )

        async with engine.begin() as connection:
            await connection.execute(
                update(CorpusDocumentModel.__table__)
                .where(CorpusDocumentModel.id == old_document_id)
                .values(active_generation=None)
            )
            await connection.execute(
                update(CorpusChunkModel.__table__)
                .where(CorpusChunkModel.id == chunk_id)
                .values(document_id=new_document_id)
            )
            await connection.execute(
                update(CorpusDocumentModel.__table__)
                .where(CorpusDocumentModel.id == new_document_id)
                .values(active_generation=1)
            )

        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text("SELECT document_id FROM corpus_chunks WHERE id = :id"),
                    {"id": chunk_id},
                )
                == new_document_id
            )
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM corpus_documents WHERE id IN (:old_id, :new_id)"),
                {"old_id": old_document_id, "new_id": new_document_id},
            )
        await engine.dispose()


@pytest.mark.integration
async def test_005_generation_reparent_rejects_invalid_new_document() -> None:
    _run_alembic("upgrade", "head")
    old_document_id = uuid.uuid4()
    new_document_id = uuid.uuid4()
    old_chunk_id = uuid.uuid4()
    new_chunk_id = uuid.uuid4()
    engine = create_engine()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                CorpusDocumentModel.__table__.insert(),
                [
                    _document_values(old_document_id, active_generation=None),
                    _document_values(new_document_id, active_generation=None),
                ],
            )
            await connection.execute(
                CorpusChunkModel.__table__.insert(),
                [
                    _chunk_values(
                        old_document_id,
                        old_chunk_id,
                        generation=1,
                        state="ACTIVE",
                        section_index=0,
                        content_hash="3" * 64,
                        embedding=[0.0] * 2560,
                    ),
                    _chunk_values(
                        new_document_id,
                        new_chunk_id,
                        generation=2,
                        state="ACTIVE",
                        section_index=0,
                        content_hash="4" * 64,
                        embedding=[0.0] * 2560,
                    ),
                ],
            )
            await connection.execute(
                update(CorpusDocumentModel.__table__)
                .where(CorpusDocumentModel.id == old_document_id)
                .values(active_generation=1)
            )
            await connection.execute(
                update(CorpusDocumentModel.__table__)
                .where(CorpusDocumentModel.id == new_document_id)
                .values(active_generation=2)
            )

        with pytest.raises(DBAPIError):
            async with engine.begin() as connection:
                await connection.execute(
                    update(CorpusDocumentModel.__table__)
                    .where(CorpusDocumentModel.id == old_document_id)
                    .values(active_generation=None)
                )
                await connection.execute(
                    update(CorpusChunkModel.__table__)
                    .where(CorpusChunkModel.id == old_chunk_id)
                    .values(document_id=new_document_id)
                )

        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text("SELECT document_id FROM corpus_chunks WHERE id = :id"),
                    {"id": old_chunk_id},
                )
                == old_document_id
            )
            assert (
                await connection.scalar(
                    text(
                        "SELECT active_generation FROM corpus_documents WHERE id = :id"
                    ),
                    {"id": old_document_id},
                )
                == 1
            )
            assert (
                await connection.scalar(
                    text(
                        "SELECT active_generation FROM corpus_documents WHERE id = :id"
                    ),
                    {"id": new_document_id},
                )
                == 2
            )
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM corpus_documents WHERE id IN (:old_id, :new_id)"),
                {"old_id": old_document_id, "new_id": new_document_id},
            )
        await engine.dispose()


@pytest.mark.integration
async def test_005_concurrent_generation_swaps_have_one_winner() -> None:
    _run_alembic("upgrade", "head")
    document_id = uuid.uuid4()
    initial_chunk_id = uuid.uuid4()
    engine = create_engine()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                CorpusDocumentModel.__table__.insert().values(
                    **_document_values(document_id, active_generation=None)
                )
            )
            await connection.execute(
                CorpusChunkModel.__table__.insert().values(
                    **_chunk_values(
                        document_id,
                        initial_chunk_id,
                        generation=1,
                        state="ACTIVE",
                        section_index=0,
                        content_hash="f" * 64,
                        embedding=[0.0] * 2560,
                    )
                )
            )
            await connection.execute(
                update(CorpusDocumentModel.__table__)
                .where(CorpusDocumentModel.id == document_id)
                .values(active_generation=1)
            )

        async def swap(generation: int, hash_character: str) -> None:
            async with engine.begin() as connection:
                await connection.execute(
                    update(CorpusChunkModel.__table__)
                    .where(CorpusChunkModel.id == initial_chunk_id)
                    .values(state="SUPERSEDED")
                )
                await connection.execute(
                    CorpusChunkModel.__table__.insert().values(
                        **_chunk_values(
                            document_id,
                            uuid.uuid4(),
                            generation=generation,
                            state="ACTIVE",
                            section_index=generation,
                            content_hash=hash_character * 64,
                            embedding=[0.0] * 2560,
                        )
                    )
                )
                await connection.execute(
                    update(CorpusDocumentModel.__table__)
                    .where(CorpusDocumentModel.id == document_id)
                    .values(active_generation=generation)
                )

        results = await asyncio.gather(
            swap(2, "1"), swap(3, "2"), return_exceptions=True
        )
        assert sum(result is None for result in results) == 1
        assert sum(isinstance(result, DBAPIError) for result in results) == 1
        async with engine.connect() as connection:
            active_generation = await connection.scalar(
                text("SELECT active_generation FROM corpus_documents WHERE id = :id"),
                {"id": document_id},
            )
            assert active_generation in {2, 3}
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM corpus_chunks "
                        "WHERE document_id = :id AND state = 'ACTIVE' "
                        "AND generation = :generation"
                    ),
                    {"id": document_id, "generation": active_generation},
                )
                == 1
            )
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM corpus_documents WHERE id = :id"),
                {"id": document_id},
            )
        await engine.dispose()


@pytest.mark.integration
async def test_005_hash_and_search_audit_checks_are_enforced() -> None:
    _run_alembic("upgrade", "head")
    document_id = uuid.uuid4()
    valid_document_id = uuid.uuid4()
    search_id = uuid.uuid4()
    engine = create_engine()
    try:
        with pytest.raises(IntegrityError):
            async with engine.begin() as connection:
                values = _document_values(document_id, active_generation=None)
                values["raw_content_hash"] = "A" * 64
                await connection.execute(
                    CorpusDocumentModel.__table__.insert().values(**values)
                )

        async with engine.begin() as connection:
            await connection.execute(
                CorpusDocumentModel.__table__.insert().values(
                    **_document_values(valid_document_id, active_generation=None)
                )
            )

        with pytest.raises(IntegrityError):
            async with engine.begin() as connection:
                await connection.execute(
                    CorpusChunkModel.__table__.insert().values(
                        **_chunk_values(
                            valid_document_id,
                            uuid.uuid4(),
                            generation=1,
                            state="STAGED",
                            section_index=0,
                            content_hash="A" * 64,
                        )
                    )
                )

        with pytest.raises(IntegrityError):
            async with engine.begin() as connection:
                await connection.execute(
                    SemanticSearchRunModel.__table__.insert().values(
                        id=search_id,
                        query_hash="a" * 64,
                        filters_sanitized={
                            "document_type": "decreto",
                            "document_subtype": "designacion_transitoria",
                            "jurisdiction": "nacion",
                            "review_status": "REVIEWED",
                            "Authorization": "blocked",
                        },
                        top_k=3,
                        minimum_score=None,
                        embedding_model="qwen3-embedding:4b-q4_K_M",
                        embedding_dimensions=2560,
                        result_count=0,
                        duration_ms=1,
                        status="SUCCEEDED",
                        request_id="request-005",
                    )
                )

        with pytest.raises(IntegrityError):
            async with engine.begin() as connection:
                await connection.execute(
                    SemanticSearchRunModel.__table__.insert().values(
                        id=uuid.uuid4(),
                        query_hash="a" * 64,
                        filters_sanitized={},
                        top_k=3,
                        minimum_score=None,
                        embedding_model="qwen3-embedding:4b-q4_K_M",
                        embedding_dimensions=2560,
                        result_count=0,
                        duration_ms=1,
                        status="FAILED",
                        request_id="request-005",
                    )
                )

        with pytest.raises(IntegrityError):
            async with engine.begin() as connection:
                await connection.execute(
                    SemanticSearchRunModel.__table__.insert().values(
                        id=uuid.uuid4(),
                        query_hash="a" * 64,
                        filters_sanitized={
                            "document_type": {"nested": "decreto"},
                            "document_subtype": "designacion_transitoria",
                            "jurisdiction": "nacion",
                            "review_status": "REVIEWED",
                        },
                        top_k=3,
                        minimum_score=None,
                        embedding_model="qwen3-embedding:4b-q4_K_M",
                        embedding_dimensions=2560,
                        result_count=0,
                        duration_ms=1,
                        status="SUCCEEDED",
                        request_id="request-005-nested",
                    )
                )

        with pytest.raises(IntegrityError):
            async with engine.begin() as connection:
                await connection.execute(
                    SemanticSearchRunModel.__table__.insert().values(
                        id=uuid.uuid4(),
                        query_hash="a" * 64,
                        filters_sanitized={
                            "document_type": "decreto",
                            "document_subtype": "designacion_transitoria",
                            "jurisdiction": "nacion",
                            "organization": "Bearer secret",
                            "review_status": "REVIEWED",
                        },
                        top_k=3,
                        minimum_score=None,
                        embedding_model="qwen3-embedding:4b-q4_K_M",
                        embedding_dimensions=2560,
                        result_count=0,
                        duration_ms=1,
                        status="SUCCEEDED",
                        request_id="request-005-sensitive",
                    )
                )

        async with engine.begin() as connection:
            await connection.execute(
                SemanticSearchRunModel.__table__.insert().values(
                    id=search_id,
                    query_hash="a" * 64,
                    filters_sanitized={
                        "document_type": "decreto",
                        "document_subtype": "designacion_transitoria",
                        "jurisdiction": "nacion",
                        "review_status": "REVIEWED",
                    },
                    top_k=3,
                    minimum_score=None,
                    embedding_model="qwen3-embedding:4b-q4_K_M",
                    embedding_dimensions=2560,
                    result_count=0,
                    duration_ms=1,
                    status="FAILED",
                    error_code="SEMANTIC_SEARCH_TIMEOUT",
                    request_id="request-005",
                )
            )
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM semantic_search_runs WHERE id = :id"),
                {"id": search_id},
            )
            await connection.execute(
                text("DELETE FROM corpus_documents WHERE id = :id"),
                {"id": valid_document_id},
            )
        await engine.dispose()

    _run_alembic("upgrade", "head")
    assert await _tables() >= NEW_TABLES


def test_migration_text_is_only_auxiliary_contract_evidence() -> None:
    migration = (
        Path(__file__).parents[2]
        / "alembic"
        / "versions"
        / "005_corpus_ingestion_semantic_retrieval.py"
    )
    text_content = migration.read_text(encoding="utf-8")
    assert 'revision = "005"' in text_content
    assert 'down_revision = "004"' in text_content
