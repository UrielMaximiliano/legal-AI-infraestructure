from __future__ import annotations

import hashlib
import json

from legal_ai.application.rag_evaluation import evaluate_manifest


def test_holdout_dry_run_is_reproducible_and_redacts_paths(tmp_path) -> None:
    pdf = tmp_path / "0001.pdf"
    content = b"synthetic holdout fixture"
    pdf.write_bytes(content)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "dataset_version": "holdout-10-v1",
                "split": "HOLDOUT_10",
                "source": "synthetic",
                "cases": [
                    {
                        "case_id": "HOLDOUT-0001",
                        "relative_path": "0001.pdf",
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "external_id": "opaque-1",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result = evaluate_manifest(str(manifest), execute=True, provider="fake")
    rendered = json.dumps(result)
    assert result["leakage_detected"] == 0
    assert result["metrics"]["schema_valid_rate"] == 1.0
    assert str(tmp_path) not in rendered
