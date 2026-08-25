"""Reproducible semantic similarity evaluators for legal answer cases."""

from .bertscore import BERTScoreConfig, BERTScoreEvaluator
from .contract import (
    CALCULATED,
    NOT_CALCULABLE,
    NORMALIZATION_NAME,
    NORMALIZATION_VERSION,
    CaseContractError,
    SemanticCase,
    normalization_metadata,
    normalize_text,
)
from .evaluator import (
    SemanticEvaluator,
    evaluate,
    evaluate_case,
    evaluate_cases,
    evaluate_semantic_case,
)
from .metrics import (
    chrf,
    chrf_details,
    chrf_score,
    rouge_l,
    rouge_l_details,
    rouge_l_score,
)

__all__ = [
    "BERTScoreConfig",
    "BERTScoreEvaluator",
    "CALCULATED",
    "CaseContractError",
    "NOT_CALCULABLE",
    "NORMALIZATION_NAME",
    "NORMALIZATION_VERSION",
    "SemanticCase",
    "SemanticEvaluator",
    "chrf",
    "chrf_details",
    "chrf_score",
    "evaluate",
    "evaluate_case",
    "evaluate_cases",
    "evaluate_semantic_case",
    "normalization_metadata",
    "normalize_text",
    "rouge_l",
    "rouge_l_details",
    "rouge_l_score",
]
