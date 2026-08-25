"""Deterministic legal-core scoring for real decree outputs."""

from .evaluator import evaluate_case, flatten_output, extract_typed_claims

__all__ = ["evaluate_case", "flatten_output", "extract_typed_claims"]
