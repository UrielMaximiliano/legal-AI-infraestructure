from __future__ import annotations

import hashlib
import json

import pytest

from legal_ai.application.rag_evaluation import (
    RagEvaluationManifestError,
    evaluate_manifest,
    load_manifest,
)


def _write_manifest(path, cases, *, split="HOLDOUT_10") -> None:
    path.write_text(
        json.dumps(
            {
                "dataset_version": "holdout-test-v1",
                "split": split,
                "source": "synthetic",
                "cases": cases,
            }
        ),
        encoding="utf-8",
    )


def test_manifest_rejects_traversal_and_wrong_split(tmp_path) -> None:
    manifest = tmp_path / "manifest.json"
    case = {
        "case_id": "H-1",
        "relative_path": "../outside.pdf",
        "sha256": "0" * 64,
        "external_id": "opaque-1",
    }
    _write_manifest(manifest, [case])
    with pytest.raises(RagEvaluationManifestError, match="PATH_INVALID"):
        load_manifest(str(manifest))
    _write_manifest(manifest, [case], split="INDEX_90")
    with pytest.raises(RagEvaluationManifestError, match="SPLIT_INVALID"):
        load_manifest(str(manifest))


def test_manifest_rejects_hash_mismatch_and_duplicate_identity(tmp_path) -> None:
    pdf = tmp_path / "case.pdf"
    content = b"holdout"
    pdf.write_bytes(content)
    valid = {
        "case_id": "H-1",
        "relative_path": "case.pdf",
        "sha256": hashlib.sha256(content).hexdigest(),
        "external_id": "opaque-1",
    }
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, [valid, {**valid, "case_id": "H-2"}])
    with pytest.raises(RagEvaluationManifestError, match="CASE_INVALID"):
        load_manifest(str(manifest))
    _write_manifest(manifest, [{**valid, "sha256": "1" * 64}])
    with pytest.raises(RagEvaluationManifestError, match="HASH_MISMATCH"):
        load_manifest(str(manifest))


def test_fake_evaluation_is_deterministic_and_ollama_is_explicitly_external(
    tmp_path,
) -> None:
    pdf = tmp_path / "case.pdf"
    content = b"holdout"
    pdf.write_bytes(content)
    manifest = tmp_path / "manifest.json"
    _write_manifest(
        manifest,
        [
            {
                "case_id": "H-1",
                "relative_path": "case.pdf",
                "sha256": hashlib.sha256(content).hexdigest(),
                "external_id": "opaque-1",
            }
        ],
    )
    first = evaluate_manifest(str(manifest), execute=True, provider="fake")
    second = evaluate_manifest(str(manifest), execute=True, provider="fake")
    assert first == second
    with pytest.raises(
        RagEvaluationManifestError, match="EXTERNAL_PROVIDER_NOT_CONFIGURED"
    ):
        evaluate_manifest(str(manifest), execute=True, provider="ollama")
