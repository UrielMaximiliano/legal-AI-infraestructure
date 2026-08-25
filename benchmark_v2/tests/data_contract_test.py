"""Executable contract tests for benchmark-v2's data layer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmark_v2.data.hashing import canonical_json, hash_records, sha256_json
from benchmark_v2.data.io import (
    HashCache,
    OptionalDependencyError,
    read_metadata,
    read_records,
    write_records,
)
from benchmark_v2.results.schema import (
    PARTIAL,
    ContractError,
    build_result,
    validate_result,
)


DATASET_HASH = "a" * 64


def metadata() -> dict[str, object]:
    return {
        "run_id": "contract-001",
        "dataset": {"name": "fixture", "version": "1", "sha256": DATASET_HASH},
        "code": {"commit": "deadbeef"},
        "generated_at_utc": "2026-08-25T12:00:00Z",
        "seed": 42,
        "dimensions": {
            "embedding_dimensions": 2560,
            "retrieval_top_k": 8,
            "hardware": "cpu",
        },
    }


def test_canonical_hash_is_stable_for_mapping_order() -> None:
    left = {"b": 2, "a": [1, {"z": True, "y": None}]}
    right = {"a": [1, {"y": None, "z": True}], "b": 2}
    assert canonical_json(left) == canonical_json(right)
    assert sha256_json(left) == sha256_json(right)


def test_build_result_preserves_dimensions_and_hashes_records() -> None:
    rows = [{"case_id": "case-1", "score": 0.8}, {"case_id": "case-2", "score": 0.9}]
    result = build_result(rows, metadata(), expected_count=2)
    assert result["status"] == "FULL"
    assert result["dimensions"]["embedding_dimensions"] == 2560
    assert result["records_sha256"] == hash_records(rows)
    assert len(result["result_sha256"]) == 64


def test_partial_is_explicit_and_full_cardinality_is_enforced() -> None:
    rows = [{"case_id": "case-1", "score": 0.8}]
    result = build_result(rows, metadata(), expected_count=2, status=PARTIAL)
    assert result["status"] == PARTIAL
    with pytest.raises(ContractError):
        build_result(rows, metadata(), expected_count=2, status="FULL")


def test_duplicate_case_ids_are_rejected() -> None:
    with pytest.raises(ContractError, match="duplicate"):
        build_result(
            [{"case_id": "case-1"}, {"case_id": "case-1"}],
            metadata(),
            expected_count=2,
        )


def test_jsonl_and_csv_round_trip_without_optional_dependencies(tmp_path: Path) -> None:
    rows = [{"case_id": "case-1", "score": 0.8}, {"case_id": "case-2", "score": 0.9}]
    jsonl = write_records(tmp_path / "rows.jsonl", rows, metadata=metadata())
    csv_path = write_records(tmp_path / "rows.csv", rows)
    assert read_records(jsonl) == rows
    assert read_records(csv_path) == [
        {"case_id": "case-1", "score": "0.8"},
        {"case_id": "case-2", "score": "0.9"},
    ]
    assert read_metadata(jsonl)["run_id"] == "contract-001"


def test_cache_is_content_addressed(tmp_path: Path) -> None:
    source = write_records(tmp_path / "rows.jsonl", [{"case_id": "case-1"}])
    cache = HashCache(tmp_path / "cache")
    cached = cache.put(source)
    assert cached.name.startswith(cache.key_for(source))
    assert cache.get(source) == cached
    assert cache.get_records(source) == [{"case_id": "case-1"}]


def test_parquet_dependency_is_optional(tmp_path: Path) -> None:
    destination = tmp_path / "rows.parquet"
    try:
        write_records(destination, [{"case_id": "case-1"}])
    except OptionalDependencyError:
        return
    assert read_records(destination) == [{"case_id": "case-1"}]


def test_schema_file_is_valid_json_and_matches_builder() -> None:
    schema_path = Path(__file__).parents[1] / "configs" / "schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["$schema"].endswith("2020-12/schema")
    assert schema["properties"]["status"]["enum"] == ["FULL", "PARTIAL"]
    assert validate_result(build_result([], metadata(), expected_count=0))["status"] == "FULL"



