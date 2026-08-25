"""Deterministic legal-core scoring for real decree outputs."""

from .evaluator import (
    EVALUATOR_VERSION,
    RULES_VERSION,
    evaluate_case,
    extract_typed_claims,
    flatten_output,
)

__all__ = [
    "EVALUATOR_VERSION",
    "RULES_VERSION",
    "evaluate_case",
    "flatten_output",
    "extract_typed_claims",
]
