from __future__ import annotations

import json
from pathlib import Path

from legal_ai.application.retrieval_evaluation import EvaluationCase, evaluate_cases


def test_fake_evaluation_is_reproducible_from_versioned_fixture() -> None:
    fixture = (
        Path(__file__).parents[1]
        / "fixtures"
        / "evaluation"
        / "005-corpus-v1"
        / "sample.json"
    )
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    cases = tuple(
        EvaluationCase(
            query_id=str(item["query_id"]),
            returned_ids=tuple(item.get("returned_ids", [])),
            relevant_ids=frozenset(item.get("relevant_ids", [])),
            latency_ms=float(item.get("latency_ms", 0)),
            usefulness_score=item.get("usefulness_score"),
            legally_relevant=item.get("legally_relevant"),
        )
        for item in payload["cases"]
    )
    first = evaluate_cases(cases, dataset_version=payload["dataset_version"])
    second = evaluate_cases(cases, dataset_version=payload["dataset_version"])
    assert first.to_dict() == second.to_dict()
    assert first.query_count == len(cases)
