"""Per-case semantic evaluation for legal answer/reference pairs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .bertscore import BERTScoreEvaluator
from .contract import (
    CALCULATED,
    NOT_CALCULABLE,
    SemanticCase,
    CaseContractError,
    normalization_metadata,
    normalize_text,
    parse_case,
)
from .metrics import chrf_details, rouge_l_details


def _not_calculable(reason: str) -> dict[str, Any]:
    return {
        "status": NOT_CALCULABLE,
        "score": None,
        "precision": None,
        "recall": None,
        "f1": None,
        "reason": reason,
    }


def _select_best(
    details: list[dict[str, Any]], score_key: str
) -> tuple[int, dict[str, Any]]:
    # max is stable for ties, so the first declared reference wins.
    best_index, best_value = max(
        enumerate(details), key=lambda item: float(item[1][score_key])
    )
    return best_index, best_value


def _invalid_record(case_id: str | None, reason: str) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "status": NOT_CALCULABLE,
        "reason": reason,
        "normalization": normalization_metadata(),
        "reference_count": 0,
        "rouge_l": _not_calculable(reason),
        "chrf": _not_calculable(reason),
        "bertscore": _not_calculable(reason),
    }


def evaluate_case(
    case: SemanticCase | Mapping[str, Any],
    *,
    bertscore: BERTScoreEvaluator | None = None,
) -> dict[str, Any]:
    """Evaluate one case while preserving NOT_CALCULABLE conditions.

    Lexical metrics select the maximum F1 over explicitly supplied references;
    ties select the first reference.  BERTScore is independent and may be
    NOT_CALCULABLE when its optional dependency is absent.
    """

    raw_case_id = (
        case.case_id
        if isinstance(case, SemanticCase)
        else case.get("case_id") if isinstance(case, Mapping) else None
    )
    case_id = raw_case_id.strip() if isinstance(raw_case_id, str) else None
    try:
        parsed = parse_case(case)
    except (CaseContractError, TypeError, AttributeError) as exc:
        return _invalid_record(case_id, str(exc))

    normalized_candidate = normalize_text(parsed.candidate)
    normalized_references = [
        normalize_text(reference) for reference in parsed.references
    ]
    if any(not reference for reference in normalized_references):
        return _invalid_record(parsed.case_id, "empty_reference")

    rouge_values = [
        rouge_l_details(normalized_candidate, reference)
        for reference in normalized_references
    ]
    rouge_index, rouge_value = _select_best(rouge_values, "f1")
    rouge_record = {
        **rouge_value,
        "status": CALCULATED,
        "score": rouge_value["f1"],
        "reason": None,
        "reference_index": rouge_index,
    }

    chrf_values = [
        chrf_details(normalized_candidate, reference)
        for reference in normalized_references
    ]
    chrf_index, chrf_value = _select_best(chrf_values, "fscore")
    chrf_record = {
        **chrf_value,
        "status": CALCULATED,
        "score": chrf_value["fscore"],
        "reason": None,
        "reference_index": chrf_index,
    }

    bertscore_evaluator = bertscore or BERTScoreEvaluator()
    bert_values = [
        bertscore_evaluator.score(normalized_candidate, reference)
        for reference in normalized_references
    ]
    if any(value.get("status") == CALCULATED for value in bert_values):
        # Re-select only calculable scores; an unavailable reference must not
        # beat a valid score merely because None is represented as zero.
        calculated = [
            (index, value)
            for index, value in enumerate(bert_values)
            if value.get("status") == CALCULATED
        ]
        bert_index, bert_record = max(
            calculated, key=lambda item: float(item[1]["f1"])
        )
        bert_record = {**bert_record, "reference_index": bert_index}
    else:
        bert_index, bert_record = 0, bert_values[0]
        bert_record = {**bert_record, "reference_index": bert_index}

    return {
        "case_id": parsed.case_id,
        "status": CALCULATED,
        "reason": None,
        "normalization": normalization_metadata(),
        "reference_count": len(parsed.references),
        "rouge_l": rouge_record,
        "chrf": chrf_record,
        "bertscore": bert_record,
    }


def evaluate_cases(
    cases: Iterable[SemanticCase | Mapping[str, Any]],
    *,
    bertscore: BERTScoreEvaluator | None = None,
) -> list[dict[str, Any]]:
    """Evaluate cases in input order without inventing aggregate results."""

    evaluator = bertscore or BERTScoreEvaluator()
    return [evaluate_case(case, bertscore=evaluator) for case in cases]


class SemanticEvaluator:
    """Reusable evaluator that keeps one optional BERTScore adapter."""

    def __init__(self, *, bertscore: BERTScoreEvaluator | None = None) -> None:
        self.bertscore = bertscore or BERTScoreEvaluator()

    def evaluate_case(self, case: SemanticCase | Mapping[str, Any]) -> dict[str, Any]:
        return evaluate_case(case, bertscore=self.bertscore)

    def evaluate(
        self, cases: Iterable[SemanticCase | Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        return [self.evaluate_case(case) for case in cases]


evaluate_semantic_case = evaluate_case
evaluate = evaluate_cases
