"""Explicit allowlist mappers between semantic-search ORM and domain objects."""

from __future__ import annotations

from typing import cast

from legal_ai.domain.semantic_search import (
    HumanRetrievalEvaluation,
    SemanticSearchRun,
    SemanticSearchStatus,
)

from .semantic_search_models import (
    HumanRetrievalEvaluationModel,
    SemanticSearchRunModel,
)


def human_evaluation_to_model(
    evaluation: HumanRetrievalEvaluation,
) -> HumanRetrievalEvaluationModel:
    return HumanRetrievalEvaluationModel(
        id=evaluation.id,
        evaluation_run_id=evaluation.evaluation_run_id,
        query_id=evaluation.query_id,
        result_document_id=evaluation.result_document_id,
        result_chunk_id=evaluation.result_chunk_id,
        evaluator_id=evaluation.evaluator_id,
        usefulness_score=evaluation.usefulness_score,
        legally_relevant=evaluation.legally_relevant,
        comments=evaluation.comments,
        dataset_version=evaluation.dataset_version,
        embedding_model=evaluation.embedding_model,
        embedding_dimensions=evaluation.embedding_dimensions,
        evaluated_at=evaluation.evaluated_at,
        created_at=evaluation.created_at,
    )


def human_evaluation_from_model(
    model: HumanRetrievalEvaluationModel,
) -> HumanRetrievalEvaluation:
    return HumanRetrievalEvaluation(
        id=model.id,
        evaluation_run_id=model.evaluation_run_id,
        query_id=model.query_id,
        result_document_id=model.result_document_id,
        result_chunk_id=model.result_chunk_id,
        evaluator_id=model.evaluator_id,
        usefulness_score=model.usefulness_score,
        legally_relevant=model.legally_relevant,
        comments=model.comments,
        dataset_version=model.dataset_version,
        embedding_model=model.embedding_model,
        embedding_dimensions=model.embedding_dimensions,
        evaluated_at=model.evaluated_at,
        created_at=model.created_at,
    )


def semantic_search_run_to_model(run: SemanticSearchRun) -> SemanticSearchRunModel:
    return SemanticSearchRunModel(
        id=run.id,
        query_hash=run.query_hash,
        filters_sanitized=run.filters_sanitized,
        top_k=run.top_k,
        minimum_score=run.minimum_score,
        embedding_model=run.embedding_model,
        embedding_dimensions=run.embedding_dimensions,
        result_count=run.result_count,
        duration_ms=run.duration_ms,
        status=SemanticSearchStatus(run.status),
        error_code=run.error_code,
        request_id=run.request_id,
        created_at=run.created_at,
    )


def semantic_search_run_from_model(model: SemanticSearchRunModel) -> SemanticSearchRun:
    return SemanticSearchRun(
        id=model.id,
        query_hash=model.query_hash,
        filters_sanitized=cast("dict[str, str]", model.filters_sanitized),
        top_k=model.top_k,
        minimum_score=model.minimum_score,
        embedding_model=model.embedding_model,
        embedding_dimensions=model.embedding_dimensions,
        result_count=model.result_count,
        duration_ms=model.duration_ms,
        status=model.status,
        error_code=model.error_code,
        request_id=model.request_id,
        created_at=model.created_at,
    )
