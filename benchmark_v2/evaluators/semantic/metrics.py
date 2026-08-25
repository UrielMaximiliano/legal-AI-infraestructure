"""Dependency-free ROUGE-L and chrF implementations.

Both functions normalize their inputs using the package contract before
scoring.  They return scalar scores through the ``*_score`` helpers and expose
precision/recall details for auditable per-case records.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Any

from .contract import normalize_text


def _f_score(precision: float, recall: float, beta: float = 1.0) -> float:
    if precision == 0.0 and recall == 0.0:
        return 0.0
    beta_squared = beta * beta
    return (1.0 + beta_squared) * precision * recall / (
        beta_squared * precision + recall
    )


def _lcs_length(left: Sequence[str], right: Sequence[str]) -> int:
    """Compute LCS length with O(len(right)) memory."""

    previous = [0] * (len(right) + 1)
    for left_token in left:
        current = [0]
        for index, right_token in enumerate(right, start=1):
            if left_token == right_token:
                current.append(previous[index - 1] + 1)
            else:
                current.append(max(previous[index], current[-1]))
        previous = current
    return previous[-1]


def rouge_l_details(candidate: str, reference: str) -> dict[str, Any]:
    """Return ROUGE-L precision, recall and F1 from whitespace-token LCS."""

    candidate_tokens = normalize_text(candidate).split()
    reference_tokens = normalize_text(reference).split()
    lcs = _lcs_length(candidate_tokens, reference_tokens)
    precision = lcs / len(candidate_tokens) if candidate_tokens else 0.0
    recall = lcs / len(reference_tokens) if reference_tokens else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": _f_score(precision, recall),
        "lcs_length": lcs,
    }


def rouge_l_score(candidate: str, reference: str) -> float:
    """Return the ROUGE-L F1 score."""

    return float(rouge_l_details(candidate, reference)["f1"])


def rouge_l(candidate: str, reference: str) -> float:
    """Alias for :func:`rouge_l_score`."""

    return rouge_l_score(candidate, reference)


def _character_ngrams(value: str, order: int) -> Counter[str]:
    if order <= 0:
        raise ValueError("character n-gram order must be positive")
    return Counter(
        value[index : index + order] for index in range(len(value) - order + 1)
    )


def chrf_details(
    candidate: str,
    reference: str,
    *,
    char_order: int = 6,
    beta: float = 2.0,
    include_whitespace: bool = True,
) -> dict[str, Any]:
    """Return chrF details using character orders 1..``char_order``.

    The implementation follows the sentence-level chrF convention: average
    precision and recall over character orders, then apply F-beta (beta=2 by
    default).  Whitespace is retained after normalization by default and is a
    declared part of the metric configuration.
    """

    if (
        not isinstance(char_order, int)
        or isinstance(char_order, bool)
        or char_order <= 0
    ):
        raise ValueError("char_order must be a positive integer")
    if beta <= 0:
        raise ValueError("beta must be positive")

    candidate_text = normalize_text(candidate)
    reference_text = normalize_text(reference)
    if not include_whitespace:
        candidate_text = candidate_text.replace(" ", "")
        reference_text = reference_text.replace(" ", "")

    # Orders longer than either sentence have no n-grams.  They are excluded
    # (rather than counted as zero), which keeps an identical short sentence
    # at chrF=1 and matches sentence-level chrF implementations.
    effective_order = min(char_order, len(candidate_text), len(reference_text))
    if effective_order == 0:
        return {
            "precision": 0.0,
            "recall": 0.0,
            "fscore": 0.0,
            "f1": 0.0,
            "beta": beta,
            "char_order": char_order,
            "include_whitespace": include_whitespace,
            "orders": [],
        }

    precisions: list[float] = []
    recalls: list[float] = []
    order_details: list[dict[str, Any]] = []
    for order in range(1, effective_order + 1):
        candidate_ngrams = _character_ngrams(candidate_text, order)
        reference_ngrams = _character_ngrams(reference_text, order)
        overlap = sum((candidate_ngrams & reference_ngrams).values())
        precision = (
            overlap / sum(candidate_ngrams.values()) if candidate_ngrams else 0.0
        )
        recall = (
            overlap / sum(reference_ngrams.values()) if reference_ngrams else 0.0
        )
        precisions.append(precision)
        recalls.append(recall)
        order_details.append(
            {
                "order": order,
                "precision": precision,
                "recall": recall,
                "overlap": overlap,
            }
        )

    precision = sum(precisions) / len(precisions)
    recall = sum(recalls) / len(recalls)
    return {
        "precision": precision,
        "recall": recall,
        "fscore": _f_score(precision, recall, beta),
        "f1": _f_score(precision, recall, beta),
        "beta": beta,
        "char_order": char_order,
        "include_whitespace": include_whitespace,
        "orders": order_details,
    }


def chrf_score(
    candidate: str,
    reference: str,
    *,
    char_order: int = 6,
    beta: float = 2.0,
    include_whitespace: bool = True,
) -> float:
    """Return the sentence-level chrF F-beta score."""

    return float(
        chrf_details(
            candidate,
            reference,
            char_order=char_order,
            beta=beta,
            include_whitespace=include_whitespace,
        )["fscore"]
    )


def chrf(
    candidate: str,
    reference: str,
    *,
    char_order: int = 6,
    beta: float = 2.0,
    include_whitespace: bool = True,
) -> float:
    """Alias for :func:`chrf_score`."""

    return chrf_score(
        candidate,
        reference,
        char_order=char_order,
        beta=beta,
        include_whitespace=include_whitespace,
    )
