from legal_ai.application.retrieval_evaluation import (
    EvaluationCase,
    evaluate_cases,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)


def test_retrieval_metrics_precision_recall_mrr_and_human_fields() -> None:
    case = EvaluationCase(
        query_id="q1",
        returned_ids=("a", "b", "c"),
        relevant_ids=frozenset({"a", "d"}),
        latency_ms=10,
        usefulness_score=4,
        legally_relevant=True,
    )
    assert precision_at_k(case.returned_ids, case.relevant_ids, 3) == 1 / 3
    assert recall_at_k(case.returned_ids, case.relevant_ids, 3) == 1 / 2
    assert reciprocal_rank(case.returned_ids, case.relevant_ids) == 1
    report = evaluate_cases((case,), dataset_version="005-corpus-v1")
    assert report.precision_at_3 == 1 / 3
    assert report.recall_at_5 == 1 / 2
    assert report.mrr == 1
    assert report.usefulness_average == 4
    assert report.legally_relevant_percent == 100
