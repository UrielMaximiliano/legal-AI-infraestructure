from __future__ import annotations

from benchmark_v2.evaluators.faithfulness import (
    CLAIM_SUPPORTED,
    CLAIM_UNSUPPORTED,
    STATUS_CALCULATED,
    STATUS_NOT_CALCULABLE,
    FaithfulnessEvaluator,
    evaluate_faithfulness,
)


def _rag_context() -> dict[str, object]:
    return {
        "trace_id": "retrieval-1",
        "chunks": [
            {
                "chunk_id": "chunk-1",
                "source_id": "doc-1",
                "text": "El tribunal confirmó la multa de 500 pesos el 3 de marzo de 2024.",
            }
        ],
        # These must not be treated as evidence by the evaluator.
        "filtered_references": [{"id": "filtered-1", "text": "La multa fue de 900 pesos."}],
    }


def test_claim_level_support_and_unsupported_claim_detection() -> None:
    result = evaluate_faithfulness(
        "El tribunal confirmó la multa de 500 pesos. La multa fue de 900 pesos.",
        _rag_context(),
    )

    assert result["status"] == STATUS_CALCULATED
    assert result["claims_supported"] == 1
    assert result["claims_unsupported"] == 1
    assert result["claims"][0]["status"] == CLAIM_SUPPORTED
    assert result["claims"][1]["status"] == CLAIM_UNSUPPORTED
    assert result["claims"][0]["evidence_ids"] == ["chunk-1"]
    assert result["unsupported_claims"] == ["La multa fue de 900 pesos."]
    assert result["faithfulness"] == 0.5


def test_not_calculable_without_traceable_rag_context_and_references_are_ignored() -> None:
    result = evaluate_faithfulness(
        {
            "answer": "La multa fue de 500 pesos.",
            "references": [{"id": "ref-1", "text": "La multa fue de 500 pesos."}],
        },
        {"references": [{"id": "ref-2", "text": "La multa fue de 500 pesos."}]},
    )

    assert result["status"] == STATUS_NOT_CALCULABLE
    assert result["faithfulness"] is None
    assert result["groundedness"] is None
    assert result["reason"] == "no_traceable_rag_context"
    assert result["evidence"] == []


def test_entailment_is_configurable_and_support_is_returned_per_evidence() -> None:
    calls: list[tuple[str, str]] = []

    def entailment(claim: str, evidence: str) -> float:
        calls.append((claim, evidence))
        return 1.0 if "contrato" in evidence else 0.0

    evaluator = FaithfulnessEvaluator(entailment, threshold=0.75, entailment_name="stub")
    result = evaluator.evaluate(
        "El contrato terminó.",
        {
            "retrieval_id": "retrieval-2",
            "chunks": [
                {"id": "c1", "text": "El contrato terminó."},
                {"id": "c2", "text": "La demanda continúa."},
            ],
        },
    )

    assert result.status == STATUS_CALCULATED
    assert result.groundedness == 1.0
    assert result["entailment"] == {"name": "stub", "threshold": 0.75}
    assert result["claims"][0]["support"] == [{"evidence_id": "c1", "score": 1.0}]
    assert calls == [("El contrato terminó.", "El contrato terminó."), ("El contrato terminó.", "La demanda continúa.")]


def test_filtered_chunks_are_not_used_as_support() -> None:
    result = evaluate_faithfulness(
        "La demanda continúa.",
        {
            "retrieval_id": "retrieval-3",
            "chunks": [
                {
                    "id": "filtered-chunk",
                    "text": "La demanda continúa.",
                    "filter_status": "filtered",
                }
            ],
        },
    )

    assert result["status"] == STATUS_NOT_CALCULABLE
    assert result["evidence"] == []


def test_unselected_chunks_are_not_used_as_support() -> None:
    result = evaluate_faithfulness(
        "La demanda continúa.",
        {
            "retrieval_id": "retrieval-4",
            "chunks": [{"id": "unselected", "text": "La demanda continúa.", "selected": False}],
        },
    )

    assert result["status"] == STATUS_NOT_CALCULABLE
    assert result["evidence"] == []
