"""Deterministic extraction and gold-based scoring for legal claims.

The package deliberately has no dependency on the application or on an LLM.
Use :func:`evaluate` for all three dimensions, or the dimension-specific
helpers when a caller already has a structured gold manifest.
"""

from .core import (
    DIMENSIONS,
    FN,
    FP,
    NOT_CALCULABLE,
    TP,
    evaluate,
    evaluate_claims,
    extract_atomic_claims,
    extract_claims,
    extract_contradictions,
    extract_entities,
    extract_legal_entities,
    score_claims,
    score_contradictions,
    score_dimension,
    score_entities,
)

__all__ = [
    "DIMENSIONS",
    "FN",
    "FP",
    "NOT_CALCULABLE",
    "TP",
    "evaluate",
    "evaluate_claims",
    "extract_atomic_claims",
    "extract_claims",
    "extract_contradictions",
    "extract_entities",
    "extract_legal_entities",
    "score_claims",
    "score_contradictions",
    "score_dimension",
    "score_entities",
]
