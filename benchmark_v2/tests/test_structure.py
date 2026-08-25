"""Unit tests for independent structural and utility benchmark metrics."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from benchmark_v2.evaluators.structure import (
    RAG_STRUCTURED_DRAFT_SCHEMA,
    aggregate_scores,
    evaluate_cases,
    score_structure,
    validate_json_schema,
)


class StructureScoreTests(unittest.TestCase):
    def test_valid_json_schema_completeness_and_format(self) -> None:
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": ["case_id", "answer"],
            "properties": {
                "case_id": {"type": "string", "minLength": 1},
                "answer": {"type": "string", "minLength": 1},
            },
            "additionalProperties": False,
        }
        result = score_structure(
            '{"case_id":"C-1","answer":"ok"}',
            schema=schema,
            expected_format="json_object",
        )

        self.assertTrue(result["json_valid"])
        self.assertTrue(result["schema_valid"])
        self.assertTrue(result["format_valid"])
        self.assertEqual(result["completeness"], 1.0)
        self.assertEqual(result["missing_fields"], [])

    def test_invalid_json_and_missing_required_fields_are_diagnostic(self) -> None:
        schema = {"type": "object", "required": ["answer"]}
        malformed = score_structure('{"answer":', schema=schema)
        incomplete = score_structure({}, schema=schema, expected_format="object")

        self.assertFalse(malformed["json_valid"])
        self.assertFalse(malformed["schema_valid"])
        self.assertEqual(malformed["completeness"], 0.0)
        self.assertFalse(incomplete["schema_valid"])
        self.assertEqual(incomplete["completeness"], 0.0)
        self.assertIn("answer", incomplete["missing_fields"])

    def test_citation_and_evidence_dimensions_do_not_hide_unknown_ids(self) -> None:
        output = {
            "sources": [
                {"citation_id": "SRC-001", "span": "A verified span"},
            ],
            "considerandos": [
                {"text": "supported", "citation_ids": ["SRC-001"]},
                {"text": "unknown", "citation_ids": ["SRC-999"]},
            ],
        }
        result = score_structure(
            output,
            expected_citations=["SRC-001", "SRC-999"],
        )

        self.assertEqual(result["citation_precision"], 0.5)
        self.assertEqual(result["citation_recall"], 1.0)
        self.assertEqual(result["invented_citation_rate"], 0.5)
        self.assertEqual(result["evidence_coverage"], 0.5)
        self.assertEqual(result["used_citations"], ["SRC-001", "SRC-999"])

    def test_default_rag_contract_and_operational_trace_are_separate(self) -> None:
        output = {
            "schema_version": 1,
            "title": "Title",
            "visto": [{"text": "Visto", "citation_ids": ["SRC-001"]}],
            "considerandos": [{"text": "Considerando", "citation_ids": ["SRC-001"]}],
            "dispositive_intro": "Dispone",
            "articles": [{"number": 1, "text": "Artículo", "citation_ids": ["SRC-001"]}],
            "closing": "Comuníquese",
            "authority": "Autoridad",
            "signature": "Firma",
            "sources": [{"citation_id": "SRC-001", "span": "span"}],
            "warnings": ["Revisión humana pendiente"],
        }
        result = score_structure(
            output,
            schema=RAG_STRUCTURED_DRAFT_SCHEMA,
            expected_citations=["SRC-001"],
            utility_score=4,
            trace={"latency_ms": 12, "cost": {"amount": 0.03, "currency": "USD"}},
        )

        self.assertTrue(result["schema_valid"])
        self.assertEqual(result["required_sections_rate"], 1.0)
        self.assertEqual(result["utility_score"], 4.0)
        self.assertEqual(result["traceability"]["latency_ms"], 12)
        self.assertEqual(result["traceability"]["cost"]["amount"], 0.03)
        self.assertNotIn("legal_score", result)
        self.assertNotIn("overall_score", result)

    def test_batch_aggregation_keeps_latency_and_cost_out_of_quality_metrics(self) -> None:
        first = score_structure({"answer": "a"}, required_fields=["answer"], latency_ms=10, cost=1)
        second = score_structure({"answer": "b"}, required_fields=["answer"], latency_ms=20, cost=3)
        result = aggregate_scores([first, second])

        self.assertEqual(result["case_count"], 2)
        self.assertEqual(result["required_sections_rate"], 1.0)
        self.assertEqual(result["traceability"]["latency_ms"]["p50"], 10)
        self.assertEqual(result["traceability"]["cost"]["total"], 4.0)
        self.assertNotIn("legal_score", result)

    def test_case_runner_accepts_per_case_expectations(self) -> None:
        result = evaluate_cases(
            [
                {"output": {"answer": "a"}, "required_fields": ["answer"]},
                {"output": {"other": "b"}, "required_fields": ["answer"]},
            ]
        )
        self.assertEqual(result["case_count"], 2)
        self.assertEqual(result["required_sections_rate"], 0.5)
        self.assertEqual(len(result["cases"]), 2)

    def test_score_schema_is_valid_json_schema(self) -> None:
        path = Path(__file__).parents[1] / "evaluators" / "structure" / "score_schema.json"
        schema = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(schema["$schema"].endswith("2020-12/schema"))
        self.assertFalse(validate_json_schema({"json_valid": True}, schema) == [])


if __name__ == "__main__":
    unittest.main()
