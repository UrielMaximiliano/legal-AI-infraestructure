"""Benchmark-v2 structural and utility evaluation."""

from .schema import (
    JSONSchema,
    RAG_STRUCTURED_DRAFT_SCHEMA,
    SchemaError,
    assert_schema_valid,
    is_schema_valid,
    required_paths,
    validate_json_schema,
)
from .scorer import (
    StructureEvaluationError,
    aggregate_scores,
    evaluate_cases,
    evaluate_structure,
    score_cases,
    score_output,
    score_structure,
)

__all__ = [
    "JSONSchema",
    "RAG_STRUCTURED_DRAFT_SCHEMA",
    "SchemaError",
    "StructureEvaluationError",
    "aggregate_scores",
    "assert_schema_valid",
    "evaluate_cases",
    "evaluate_structure",
    "is_schema_valid",
    "required_paths",
    "score_cases",
    "score_output",
    "score_structure",
    "validate_json_schema",
]
