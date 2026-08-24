from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "evaluate_decree_factual_fidelity.py"
SPEC = importlib.util.spec_from_file_location("factual_fidelity", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
EVALUATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVALUATOR)


class FactualFidelityEvaluatorTests(unittest.TestCase):
    def test_prompt_manifest_binds_case_pdf_hash_and_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prompts = root / "prompts"
            prompts.mkdir()
            (prompts / "prompt-0001-123.md").write_text("Prompt legal\n", encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps({
                    "records": [{
                        "case_id": "HOLDOUT-0001",
                        "prompt_file": "prompt-0001-123.md",
                        "source_pdf": "123.pdf",
                        "source_sha256": "a" * 64,
                    }]
                }),
                encoding="utf-8",
            )

            loaded = EVALUATOR._load_prompt_manifest(manifest, prompts, 1)

            self.assertEqual(loaded[1]["reference_pdf"], "123.pdf")
            self.assertEqual(loaded[1]["reference_sha256"], "a" * 64)
            self.assertEqual(loaded[1]["prompt_text"], "Prompt legal")
            self.assertEqual(len(loaded[1]["prompt_sha256"]), 64)

    def test_missing_output_scores_zero_and_adds_false_negatives(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "run" / "cases").mkdir(parents=True)
            prompt = "Prorrogar por 180 días el Decreto 10/2020."
            reference = {
                "reference_pdf": "123.pdf",
                "reference_sha256": "a" * 64,
                "field_candidates": {
                    "objeto": "Prorrogar por 180 días el Decreto 10/2020."
                },
            }
            prompt_cases = {
                1: {
                    "reference_pdf": "123.pdf",
                    "reference_sha256": "a" * 64,
                    "prompt_text": prompt,
                    "prompt_sha256": "b" * 64,
                }
            }
            summary, rows = EVALUATOR.evaluate_run(
                {"case_id": "C01", "path": "run"},
                root,
                {"123.pdf": reference},
                prompt_cases,
                1,
                {},
            )

            self.assertEqual(rows[0]["status"], "MISSING")
            self.assertEqual(rows[0]["factual_fidelity"], 0.0)
            self.assertGreater(rows[0]["fn"], 0)
            self.assertEqual(summary["factual_fidelity_e2e"], 0.0)
            self.assertFalse(summary["comparable_full_run"])

    def test_case_filename_must_match_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cases = Path(directory)
            (cases / "case-0001.json").write_text(
                json.dumps({"case_number": 2}), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "filename/case_number mismatch"):
                EVALUATOR._load_run_cases(cases, 2)


if __name__ == "__main__":
    unittest.main()
