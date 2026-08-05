import uuid
from dataclasses import fields
from datetime import UTC, datetime, timedelta

import pytest

from legal_ai.domain.ingestion import (
    EmbeddingBatch,
    EmbeddingBatchStatus,
    IngestionRun,
    IngestionRunStatus,
    IngestionRunTransitionError,
    IngestionRunType,
)
from legal_ai.domain.semantic_search import (
    HumanRetrievalEvaluation,
    SearchFilters,
    SemanticSearchRun,
    SemanticSearchStatus,
)


def _run_snapshot(run: IngestionRun) -> dict[str, object]:
    observable_fields = (
        "id",
        "run_id",
        "run_type",
        "status",
        "processed_documents",
        "processed_chunks",
        "started_at",
        "finished_at",
        "resumed_at",
        "resume_count",
        "error_code",
        "source_identifier",
        "configuration_hash",
        "configuration_snapshot",
        "counts",
        "heartbeat_at",
        "error_summary",
    )
    snapshot = {name: getattr(run, name) for name in observable_fields}
    assert set(snapshot) == {field.name for field in fields(run)}
    return snapshot


def test_ingestion_states_and_batch_invariants() -> None:
    run = IngestionRun(uuid.uuid4(), "run-1", IngestionRunType.INGEST)
    assert run.status is IngestionRunStatus.PENDING
    run.start()
    assert run.status is IngestionRunStatus.RUNNING
    run.finish(IngestionRunStatus.COMPLETED)
    assert run.status is IngestionRunStatus.COMPLETED
    assert set(IngestionRunStatus) == {
        IngestionRunStatus.PENDING,
        IngestionRunStatus.RUNNING,
        IngestionRunStatus.COMPLETED,
        IngestionRunStatus.PARTIAL,
        IngestionRunStatus.FAILED,
        IngestionRunStatus.INTERRUPTED,
    }
    assert set(EmbeddingBatchStatus) == {
        EmbeddingBatchStatus.PENDING,
        EmbeddingBatchStatus.PROCESSING,
        EmbeddingBatchStatus.SUCCEEDED,
        EmbeddingBatchStatus.FAILED_RETRYABLE,
        EmbeddingBatchStatus.FAILED_FINAL,
    }
    with pytest.raises(ValueError):
        EmbeddingBatch(uuid.uuid4(), uuid.uuid4(), 0, 0, 1)
    batch = EmbeddingBatch(uuid.uuid4(), uuid.uuid4(), 1, 0, 1)
    batch.transition(EmbeddingBatchStatus.PROCESSING)
    batch.transition(EmbeddingBatchStatus.FAILED_RETRYABLE)
    batch.transition(EmbeddingBatchStatus.PROCESSING)
    batch.transition(EmbeddingBatchStatus.SUCCEEDED)
    with pytest.raises(ValueError):
        batch.transition(EmbeddingBatchStatus.PROCESSING)


def test_ingestion_run_rejects_pending_to_completed() -> None:
    run = IngestionRun(uuid.uuid4(), "run-pending", IngestionRunType.INGEST)
    before = _run_snapshot(run)

    with pytest.raises(
        IngestionRunTransitionError, match="INVALID_INGESTION_RUN_TRANSITION"
    ):
        run.finish(IngestionRunStatus.COMPLETED)
    assert _run_snapshot(run) == before


def test_ingestion_run_invalid_finish_is_fully_atomic() -> None:
    started_at = datetime(2026, 8, 4, 12, tzinfo=UTC)
    run = IngestionRun(uuid.uuid4(), "run-atomic", IngestionRunType.INGEST)
    run.start(at=started_at)
    before = _run_snapshot(run)

    with pytest.raises(
        IngestionRunTransitionError, match="INVALID_INGESTION_RUN_TRANSITION"
    ):
        run.finish("FAILED", error_code="MUTATED")  # type: ignore[arg-type]

    assert _run_snapshot(run) == before


@pytest.mark.parametrize(
    ("target", "error_code", "expected_error"),
    [
        ("NOT_A_STATUS", None, IngestionRunTransitionError),
        (IngestionRunStatus.FAILED, "lowercase", ValueError),
        (IngestionRunStatus.FAILED, None, ValueError),
    ],
)
def test_ingestion_run_late_validation_failures_do_not_mutate(
    target: object,
    error_code: str | None,
    expected_error: type[Exception],
) -> None:
    run = IngestionRun(uuid.uuid4(), "run-late-validation", IngestionRunType.INGEST)
    run.start(at=datetime(2026, 8, 4, 12, tzinfo=UTC))
    before = _run_snapshot(run)

    with pytest.raises(expected_error):
        run.finish(target, error_code=error_code)  # type: ignore[arg-type]

    assert _run_snapshot(run) == before


@pytest.mark.parametrize(
    "terminal_status",
    [
        IngestionRunStatus.COMPLETED,
        IngestionRunStatus.PARTIAL,
        IngestionRunStatus.FAILED,
    ],
)
def test_ingestion_run_terminal_states_cannot_be_rewritten(
    terminal_status: IngestionRunStatus,
) -> None:
    started_at = datetime(2026, 8, 4, 12, tzinfo=UTC)
    finished_at = started_at + timedelta(seconds=5)
    run = IngestionRun(uuid.uuid4(), "run-terminal", IngestionRunType.INGEST)
    run.start(at=started_at)
    run.finish(
        terminal_status,
        at=finished_at,
        error_code="INGESTION_FAILED"
        if terminal_status is IngestionRunStatus.FAILED
        else None,
    )

    assert run.started_at == started_at
    assert run.finished_at == finished_at
    for target in IngestionRunStatus:
        before = _run_snapshot(run)
        with pytest.raises(IngestionRunTransitionError):
            if target is IngestionRunStatus.RUNNING:
                run.resume(at=finished_at + timedelta(seconds=1))
            else:
                run.finish(target, at=finished_at + timedelta(seconds=1))
        assert _run_snapshot(run) == before
    assert run.status is terminal_status
    assert run.finished_at == finished_at


@pytest.mark.parametrize(
    "terminal_status", [IngestionRunStatus.COMPLETED, IngestionRunStatus.FAILED]
)
def test_terminal_finish_rejection_has_individual_full_snapshot(
    terminal_status: IngestionRunStatus,
) -> None:
    run = IngestionRun(uuid.uuid4(), "run-terminal-finish", IngestionRunType.INGEST)
    run.start(at=datetime(2026, 8, 4, 12, tzinfo=UTC))
    run.finish(
        terminal_status,
        error_code="INGESTION_FAILED"
        if terminal_status is IngestionRunStatus.FAILED
        else None,
    )
    before = _run_snapshot(run)
    with pytest.raises(IngestionRunTransitionError):
        run.finish(IngestionRunStatus.FAILED, error_code="MUTATED")
    assert _run_snapshot(run) == before


def test_ingestion_run_interrupted_resume_preserves_error_information() -> None:
    started_at = datetime(2026, 8, 4, 12, tzinfo=UTC)
    resumed_at = started_at + timedelta(seconds=10)
    completed_at = resumed_at + timedelta(seconds=10)
    run = IngestionRun(uuid.uuid4(), "run-resume", IngestionRunType.REINDEX)
    run.start(at=started_at)
    run.finish(
        IngestionRunStatus.INTERRUPTED,
        at=started_at + timedelta(seconds=5),
        error_code="EMBEDDING_PROVIDER_UNAVAILABLE",
    )

    assert run.finished_at is None
    before_invalid_finish = _run_snapshot(run)
    with pytest.raises(IngestionRunTransitionError):
        run.finish(IngestionRunStatus.COMPLETED, at=resumed_at)
    assert _run_snapshot(run) == before_invalid_finish

    run.resume(at=resumed_at)
    assert run.status is IngestionRunStatus.RUNNING
    assert run.resume_count == 1
    assert run.error_code == "EMBEDDING_PROVIDER_UNAVAILABLE"
    assert run.started_at == started_at

    run.finish(IngestionRunStatus.COMPLETED, at=completed_at)
    assert run.finished_at == completed_at
    assert run.error_code == "EMBEDDING_PROVIDER_UNAVAILABLE"


def test_ingestion_run_rejects_resume_from_non_resumable_state_and_double_finish() -> (
    None
):
    run = IngestionRun(uuid.uuid4(), "run-double-finish", IngestionRunType.INGEST)
    before_invalid_resume = _run_snapshot(run)
    with pytest.raises(IngestionRunTransitionError):
        run.resume()
    assert _run_snapshot(run) == before_invalid_resume

    run.start()
    run.finish(IngestionRunStatus.COMPLETED)
    first_finished_at = run.finished_at
    before_double_finish = _run_snapshot(run)
    with pytest.raises(IngestionRunTransitionError):
        run.finish(IngestionRunStatus.FAILED, error_code="INGESTION_FAILED")
    assert _run_snapshot(run) == before_double_finish
    assert run.finished_at == first_finished_at


def test_ingestion_run_rejects_arbitrary_states_and_exposes_safe_snapshot() -> None:
    with pytest.raises(ValueError, match="INGESTION_RUN_STATE_INVALID"):
        IngestionRun(
            uuid.uuid4(),
            "run-invalid",
            IngestionRunType.INGEST,
            status="RUNNING",  # type: ignore[arg-type]
        )

    run = IngestionRun(uuid.uuid4(), "run-safe", IngestionRunType.INGEST)
    run.start()
    run.finish(IngestionRunStatus.FAILED, error_code="CORPUS_PARSE_FAILED")
    snapshot = run.to_safe_dict()

    assert snapshot["status"] == "FAILED"
    assert snapshot["error_code"] == "CORPUS_PARSE_FAILED"
    assert not {
        "raw_content",
        "normalized_content",
        "Authorization",
        "token",
        "storage_path",
    }.intersection(snapshot)


def test_search_audit_is_minimized_and_filters_sanitized() -> None:
    filters = SearchFilters(
        jurisdiction="nacion",
        document_type="decreto",
        document_subtype="designacion_transitoria",
        language="es",
        organization="organismo",
    )
    assert filters.sanitized() == {
        "jurisdiction": "nacion",
        "document_type": "decreto",
        "document_subtype": "designacion_transitoria",
        "language": "es",
        "organization": "organismo",
        "review_status": "REVIEWED",
    }
    run = SemanticSearchRun(
        id=uuid.uuid4(),
        query_hash="a" * 64,
        filters_sanitized=filters.sanitized(),
        top_k=3,
        minimum_score=0.0,
        embedding_model="qwen3-embedding:0.6b",
        embedding_dimensions=1024,
        result_count=1,
        duration_ms=2,
        status=SemanticSearchStatus.SUCCEEDED,
        request_id="request-005",
    )
    assert "query" not in run.__dict__ if hasattr(run, "__dict__") else True


@pytest.mark.parametrize(
    "filters",
    [
        {"Authorization": "Bearer secret"},
        {"token": "secret"},
        {"query": "texto"},
        {"storage_path": "C:/interno"},
        {"raw_content": "contenido"},
        {"normalized_content": "contenido"},
        {"embedding": [0.0]},
        {"vector": [0.0]},
        {"unknown": "value"},
    ],
)
def test_search_audit_rejects_uncontracted_filters(
    filters: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="INVALID_SEMANTIC_SEARCH_FILTERS"):
        SemanticSearchRun(
            id=uuid.uuid4(),
            query_hash="a" * 64,
            filters_sanitized=filters,
            top_k=3,
            minimum_score=None,
            embedding_model="qwen3-embedding:0.6b",
            embedding_dimensions=1024,
            result_count=0,
            duration_ms=1,
            status=SemanticSearchStatus.FAILED,
            error_code="SEMANTIC_SEARCH_TIMEOUT",
            request_id="request-005",
        )


def test_search_audit_timeout_is_failed_with_required_error() -> None:
    run = SemanticSearchRun(
        id=uuid.uuid4(),
        query_hash="b" * 64,
        filters_sanitized={
            "document_type": "decreto",
            "document_subtype": "designacion_transitoria",
            "jurisdiction": "nacion",
            "review_status": "REVIEWED",
        },
        top_k=3,
        minimum_score=None,
        embedding_model="qwen3-embedding:0.6b",
        embedding_dimensions=1024,
        result_count=0,
        duration_ms=1,
        status=SemanticSearchStatus.FAILED,
        error_code="SEMANTIC_SEARCH_TIMEOUT",
        request_id="request-005",
    )
    assert run.status is SemanticSearchStatus.FAILED


def test_search_audit_requires_request_id_and_failed_error() -> None:
    required_filters = {
        "document_type": "decreto",
        "document_subtype": "designacion_transitoria",
        "jurisdiction": "nacion",
        "review_status": "REVIEWED",
    }
    with pytest.raises(ValueError, match="SEMANTIC_SEARCH_QUERY_HASH_INVALID"):
        SemanticSearchRun(
            id=uuid.uuid4(),
            query_hash="A" * 64,
            filters_sanitized=required_filters,
            top_k=3,
            minimum_score=None,
            embedding_model="qwen3-embedding:0.6b",
            embedding_dimensions=1024,
            result_count=0,
            duration_ms=1,
            status=SemanticSearchStatus.SUCCEEDED,
            request_id="request-005",
        )
    with pytest.raises(ValueError, match="SEMANTIC_SEARCH_REQUEST_ID_INVALID"):
        SemanticSearchRun(
            id=uuid.uuid4(),
            query_hash="c" * 64,
            filters_sanitized=required_filters,
            top_k=3,
            minimum_score=None,
            embedding_model="qwen3-embedding:0.6b",
            embedding_dimensions=1024,
            result_count=0,
            duration_ms=1,
            status=SemanticSearchStatus.SUCCEEDED,
            request_id=" ",
        )
    with pytest.raises(ValueError, match="SEMANTIC_SEARCH_ERROR_CODE_INVALID"):
        SemanticSearchRun(
            id=uuid.uuid4(),
            query_hash="d" * 64,
            filters_sanitized=required_filters,
            top_k=3,
            minimum_score=None,
            embedding_model="qwen3-embedding:0.6b",
            embedding_dimensions=1024,
            result_count=0,
            duration_ms=1,
            status=SemanticSearchStatus.FAILED,
            request_id="request-005",
        )


def test_search_filters_require_and_normalize_mvp_values() -> None:
    filters = SearchFilters(
        document_type=" Decreto ",
        document_subtype="Designación transitoria",
        jurisdiction="NACIÓN",
        language=" ES ",
        organization="  Ministerio   de Justicia ",
    )

    assert filters.sanitized() == {
        "document_type": "decreto",
        "document_subtype": "designacion_transitoria",
        "jurisdiction": "nacion",
        "language": "es",
        "organization": "Ministerio de Justicia",
        "review_status": "REVIEWED",
    }


@pytest.mark.parametrize(
    ("document_type", "document_subtype", "jurisdiction"),
    [
        (None, "designacion_transitoria", "nacion"),
        ("decreto", None, "nacion"),
        ("decreto", "designacion_transitoria", None),
        ("", "designacion_transitoria", "nacion"),
        ("decreto", "   ", "nacion"),
        ("decreto", "designacion_transitoria", "\t"),
        ("resolucion", "designacion_transitoria", "nacion"),
        ("decreto", "licencia", "nacion"),
        ("decreto", "designacion_transitoria", "provincia"),
    ],
)
def test_search_filters_reject_missing_blank_or_invalid_mvp_values(
    document_type: str | None,
    document_subtype: str | None,
    jurisdiction: str | None,
) -> None:
    with pytest.raises(ValueError, match="INVALID_SEMANTIC_SEARCH_FILTERS"):
        SearchFilters(
            document_type=document_type,
            document_subtype=document_subtype,
            jurisdiction=jurisdiction,
        )


def test_pending_review_requires_explicit_administrative_filter() -> None:
    with pytest.raises(ValueError, match="INVALID_SEMANTIC_SEARCH_FILTERS"):
        SearchFilters(
            document_type="decreto",
            document_subtype="designacion_transitoria",
            jurisdiction="nacion",
            reviewed_only=False,
        )

    filters = SearchFilters(
        document_type="decreto",
        document_subtype="designacion_transitoria",
        jurisdiction="nacion",
        review_status="PENDING_REVIEW",
        reviewed_only=False,
    )
    assert filters.sanitized()["review_status"] == "PENDING_REVIEW"


@pytest.mark.parametrize(
    "hostile_filters",
    [
        {"document_type": {"Authorization": "secret"}},
        {"jurisdiction": ["nacion"]},
        {"organization": {"token": "x"}},
        {"language": ("es",)},
        {"review_status": {"REVIEWED"}},
        {"document_type": object()},
        {"minimum_score": float("nan")},
        {"organization": float("nan")},
        {"organization": float("inf")},
        {"organization": float("-inf")},
        {"document_type": "decreto", "organization": "Authorization Bearer x"},
        {"document_type": "decreto", "organization": "token=x"},
        {"document_type": "decreto", "organization": "x" * 201},
    ],
)
def test_search_audit_rejects_nested_ambiguous_or_sensitive_filter_values(
    hostile_filters: dict[str, object],
) -> None:
    filters: dict[str, object] = {
        "document_type": "decreto",
        "document_subtype": "designacion_transitoria",
        "jurisdiction": "nacion",
        "review_status": "REVIEWED",
    }
    filters.update(hostile_filters)

    with pytest.raises(ValueError, match="INVALID_SEMANTIC_SEARCH_FILTERS"):
        SemanticSearchRun(
            id=uuid.uuid4(),
            query_hash="a" * 64,
            filters_sanitized=filters,
            top_k=3,
            minimum_score=None,
            embedding_model="qwen3-embedding:0.6b",
            embedding_dimensions=1024,
            result_count=0,
            duration_ms=1,
            status=SemanticSearchStatus.SUCCEEDED,
            request_id="request-005",
        )


def test_human_evaluation_contract_and_invariants() -> None:
    evaluation = HumanRetrievalEvaluation(
        id=uuid.uuid4(),
        evaluation_run_id=uuid.uuid4(),
        query_id="fixture-query-1",
        result_document_id=uuid.uuid4(),
        result_chunk_id=uuid.uuid4(),
        evaluator_id="evaluator-1",
        usefulness_score=5,
        legally_relevant=True,
        dataset_version="005-v1",
        embedding_model="qwen3-embedding:0.6b",
        embedding_dimensions=1024,
        comments="  comentario\nseguro  ",
    )
    assert evaluation.comments == "comentario seguro"
    with pytest.raises(ValueError):
        HumanRetrievalEvaluation(
            id=uuid.uuid4(),
            evaluation_run_id=uuid.uuid4(),
            query_id="query",
            result_document_id=uuid.uuid4(),
            result_chunk_id=uuid.uuid4(),
            evaluator_id="evaluator",
            usefulness_score=6,
            legally_relevant=False,
            dataset_version="v1",
            embedding_model="qwen3-embedding:0.6b",
            embedding_dimensions=1024,
        )
