"""Compatibility imports for callers that keep metrics separate from scoring."""

from .scorer import aggregate_scores, evaluate_cases, score_cases, score_output, score_structure

__all__ = [
    "aggregate_scores",
    "evaluate_cases",
    "score_cases",
    "score_output",
    "score_structure",
]
