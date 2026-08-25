"""Unit tests for the dependency-free benchmark-v2 retrieval evaluator."""

from __future__ import annotations

from hashlib import sha256

import pytest

from benchmark_v2.evaluators.retrieval import (
    compare_full_partial,
    detect_leakage,
    evaluate_chunk_quality,
    evaluate_retrieval,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
    validate_corpus_exclusion,
    validate_provenance,
)


def chunk(chunk_id: str, *, document_id: str = "doc-1", text: str = "legal text", **extra: object) -> dict[str, object]:
    return {
        "chunk_id": chunk_id,
        "document_id": document_id,
        "text": text,
        "source": "corpus-main",
        "corpus_id": "main",
        **extra,
    }


def case(query_id: str, retrieved: list[str], relevant: object = ("gold",)) -> dict[str, object]:
    return {"query_id": query_id, "retrieved": retrieved, "relevance": relevant}


def test_recall_mrr_and_ndcg_use_rank_and_return_none_without_reference() -> None:
    retrieved = ["wrong", "gold", "other"]
    assert recall_at_k(retrieved, {"gold"}, 1) == 0.0
    assert recall_at_k(retrieved, {"gold"}, 2) == 1.0
    assert reciprocal_rank(retrieved, {"gold"}) == 0.5
    assert ndcg_at_k(["gold", "wrong"], {"gold": 3, "other": 1}, 2) == pytest.approx(0.8262346571)
    assert recall_at_k(retrieved, None, 3) is None
    assert reciprocal_rank(retrieved, (),) is None


def test_metric_evaluation_preserves_missing_reference_cases() -> None:
    result = evaluate_retrieval(
        [case("q1", ["gold"], {"gold": 1}), case("q2", ["gold"], None)],
        ks=(1,),
    )
    assert result.status == "PARTIAL"
    assert result.metrics["recall_at_1"].value == 1.0
    assert result.metrics["recall_at_1"].missing_query_ids == ("q2",)
    assert result.records[1]["recall_at_1"] is None


def test_chunk_quality_and_provenance_report_failures_without_throwing() -> None:
    content = "traceable content"
    good = chunk("c1", text=content, content_hash=sha256(content.encode()).hexdigest())
    bad = {"chunk_id": "c2", "text": ""}
    quality = evaluate_chunk_quality([good, bad])
    assert quality.valid_count == 1
    assert "missing_document_id" in quality.chunks[1].issues
    report = validate_provenance([good, bad])
    assert not report.ok
    assert any(item.code == "missing_provenance" for item in report.violations)


def test_corpus_exclusion_and_leakage_are_explicit() -> None:
    holdout = chunk("c-holdout", split="HOLDOUT_10")
    excluded = validate_corpus_exclusion([holdout])
    assert not excluded.passed
    leaked = detect_leakage([chunk("c1", text="same query")], queries=[{"query_id": "q1", "query": "same query"}])
    assert not leaked.passed
    assert leaked.leakage_count >= 1


def test_full_partial_comparison_exposes_missing_ids_and_common_metrics() -> None:
    full = {"status": "FULL", "expected_count": 3, "records": [
        case("q1", ["a"], {"a": 1}),
        case("q2", ["b"], {"b": 1}),
        case("q3", ["wrong"], {"c": 1}),
    ]}
    partial = {"status": "PARTIAL", "expected_count": 3, "records": full["records"][:2]}
    comparison = compare_full_partial(full, partial, ks=(1,))
    assert comparison.status == "PARTIAL"
    assert comparison.missing_in_partial == ("q3",)
    assert comparison.coverage == pytest.approx(2 / 3)
    metric = comparison.metrics["recall_at_1"]
    assert metric.full == pytest.approx(2 / 3)
    assert metric.partial == 1.0
    assert metric.missing_in_partial == ("q3",)


def test_full_cardinality_is_not_silently_accepted() -> None:
    with pytest.raises(ValueError):
        compare_full_partial(
            {"status": "FULL", "expected_count": 2, "records": [case("q1", ["a"])]},
            {"status": "PARTIAL", "records": []},
        )
