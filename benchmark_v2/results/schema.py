"""Runtime validation and builders for benchmark-v2 result envelopes.

The JSON Schema in ``benchmark_v2/configs/schema.json`` is the interchange
contract.  This module mirrors the small amount of semantic validation that a
JSON Schema validator cannot express conveniently: FULL/PARTIAL coverage,
duplicate case identifiers, and reproducibility metadata.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Sequence

from ..data.hashing import canonicalize, hash_records, sha256_json


SCHEMA_VERSION = "benchmark-v2.result.v1"
STATUS_FULL = "FULL"
STATUS_PARTIAL = "PARTIAL"
FULL = STATUS_FULL
PARTIAL = STATUS_PARTIAL
VALID_STATUSES = frozenset({STATUS_FULL, STATUS_PARTIAL})
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class ContractError(ValueError):
    """Raised when a result or metadata envelope violates the contract."""


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{label} must be an object")
    return dict(value)


def _nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} must be a non-empty string")
    return value


def _digest(value: Any, label: str) -> str:
    result = _nonempty_string(value, label).lower()
    if not _SHA256_RE.fullmatch(result):
        raise ContractError(f"{label} must be a lowercase or uppercase SHA-256 digest")
    return result


def _timestamp(value: Any, label: str) -> str:
    text = _nonempty_string(value, label)
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{label} must be an RFC-3339 timestamp") from exc
    return text


def _scalar(value: Any, label: str) -> Any:
    if value is None or isinstance(value, (str, int, bool, float)):
        if isinstance(value, float) and (value != value or value in {float("inf"), float("-inf")}):
            raise ContractError(f"{label} must not be NaN or infinite")
        return value
    raise ContractError(f"{label} must be a scalar dimension value")


def validate_dimensions(value: Any, *, label: str = "dimensions") -> dict[str, Any]:
    """Validate an arbitrary-dimensional coordinate mapping."""

    dimensions = _require_mapping(value, label)
    return {str(key): _scalar(item, f"{label}.{key}") for key, item in dimensions.items()}


def _find_first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def validate_metadata(metadata: Mapping[str, Any], *, require_run_id: bool = True) -> dict[str, Any]:
    """Validate and return reproducibility metadata.

    Both the nested names used by the README (``dataset.sha256`` and
    ``code.commit``) and flat aliases (``dataset_hash`` / ``git_commit``) are
    accepted.  The returned mapping preserves caller fields while normalising
    the canonical aliases.
    """

    value = _require_mapping(metadata, "metadata")
    if require_run_id:
        _nonempty_string(_find_first(value, "run_id", "id"), "metadata.run_id")

    dataset = _find_first(value, "dataset")
    if dataset is not None:
        dataset_value = _require_mapping(dataset, "metadata.dataset")
        _nonempty_string(
            _find_first(dataset_value, "name", "id"), "metadata.dataset.name"
        )
        _nonempty_string(
            _find_first(dataset_value, "version", "revision"),
            "metadata.dataset.version",
        )
        dataset_hash = _find_first(dataset_value, "sha256", "hash", "digest")
        if dataset_hash is not None:
            _digest(dataset_hash, "metadata.dataset.sha256")
    else:
        dataset_hash = _find_first(value, "dataset_hash", "data_hash", "input_hash")
        if dataset_hash is None:
            raise ContractError("metadata requires dataset or dataset_hash")
        _digest(dataset_hash, "metadata.dataset_hash")

    code = _find_first(value, "code")
    if code is not None:
        code_value = _require_mapping(code, "metadata.code")
        _nonempty_string(
            _find_first(code_value, "commit", "version", "revision"),
            "metadata.code.commit",
        )
    else:
        _nonempty_string(
            _find_first(value, "code_version", "git_commit", "commit"),
            "metadata.code_version",
        )

    timestamp = _find_first(value, "generated_at_utc", "generated_at", "timestamp")
    _timestamp(timestamp, "metadata.generated_at_utc")
    seed = value.get("seed")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ContractError("metadata.seed must be an integer")
    dimensions = value.get("dimensions", value.get("dimension_values"))
    if dimensions is None:
        raise ContractError("metadata.dimensions is required")
    validate_dimensions(dimensions, label="metadata.dimensions")

    # Canonical aliases make downstream consumers independent of the chosen
    # spelling while retaining the original nested metadata for auditability.
    normalized = canonicalize(value)
    normalized["run_id"] = str(_find_first(value, "run_id", "id"))
    normalized["generated_at_utc"] = str(timestamp)
    normalized["dimensions"] = validate_dimensions(dimensions)
    normalized["seed"] = seed
    return normalized


def _records_from(value: Mapping[str, Any]) -> list[dict[str, Any]]:
    records = _find_first(value, "records", "results", "rows", "cases")
    if records is None:
        raise ContractError("result requires records (or results/rows/cases)")
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes, bytearray)):
        raise ContractError("result.records must be an array")
    result = []
    for index, record in enumerate(records):
        item = _require_mapping(record, f"result.records[{index}]")
        if "dimensions" in item:
            validate_dimensions(item["dimensions"], label=f"result.records[{index}].dimensions")
        result.append(canonicalize(item))
    return result


def _status(value: Any, *, record_count: int, expected_count: int | None) -> str:
    if value is None:
        if expected_count is not None and record_count == expected_count:
            return STATUS_FULL
        return STATUS_PARTIAL
    if not isinstance(value, str) or value.upper() not in VALID_STATUSES:
        raise ContractError("status must be FULL or PARTIAL")
    status = value.upper()
    if status == STATUS_FULL and expected_count is not None and record_count != expected_count:
        raise ContractError(
            f"FULL result has {record_count} records but expected {expected_count}"
        )
    return status


def validate_result(result: Mapping[str, Any], *, require_hashes: bool = False) -> dict[str, Any]:
    """Validate a result envelope and return its canonical representation."""

    value = _require_mapping(result, "result")
    metadata_value = _find_first(value, "metadata", "run_metadata")
    if metadata_value is None:
        # A few producers put metadata fields at the envelope root.  Promote
        # them for validation while keeping the original fields below.
        metadata_value = {
            key: value[key]
            for key in (
                "run_id", "dataset", "dataset_hash", "data_hash", "input_hash",
                "code", "code_version", "git_commit", "commit",
                "generated_at_utc", "generated_at", "timestamp", "seed",
                "dimensions", "dimension_values",
            )
            if key in value
        }
    metadata = validate_metadata(metadata_value)
    if "run_id" in value and value["run_id"] != metadata["run_id"]:
        raise ContractError("result.run_id must match metadata.run_id")
    if "schema_version" in value and value["schema_version"] != SCHEMA_VERSION:
        raise ContractError(f"schema_version must be {SCHEMA_VERSION!r}")
    records = _records_from(value)
    expected_raw = _find_first(value, "expected_count", "expected_records", "total_expected")
    expected_count: int | None = None
    if expected_raw is not None:
        if not isinstance(expected_raw, int) or isinstance(expected_raw, bool) or expected_raw < 0:
            raise ContractError("expected_count must be a non-negative integer")
        expected_count = expected_raw
    status = _status(
        _find_first(value, "status", "completeness", "run_status"),
        record_count=len(records),
        expected_count=expected_count,
    )
    dimensions = value.get("dimensions", metadata["dimensions"])
    dimensions = validate_dimensions(dimensions)

    identifiers: list[str] = []
    for index, record in enumerate(records):
        identifier = _find_first(record, "record_id", "case_id", "id")
        if identifier is not None:
            identifier_text = _nonempty_string(identifier, f"result.records[{index}].id")
            identifiers.append(identifier_text)
    if len(identifiers) != len(set(identifiers)):
        raise ContractError("result records contain duplicate identifiers")

    calculated_records_hash = hash_records(records)
    supplied_records_hash = _find_first(value, "records_sha256", "data_sha256")
    if require_hashes:
        _digest(supplied_records_hash, "result.records_sha256")
        _digest(_find_first(value, "result_sha256"), "result.result_sha256")
    if supplied_records_hash is not None and supplied_records_hash.lower() != calculated_records_hash:
        raise ContractError("result.records_sha256 does not match records")

    normalized = canonicalize(value)
    normalized["schema_version"] = str(value.get("schema_version", SCHEMA_VERSION))
    normalized["status"] = status
    normalized["metadata"] = metadata
    normalized["dimensions"] = dimensions
    normalized["records"] = records
    if expected_count is not None:
        normalized["expected_count"] = expected_count
    normalized["records_sha256"] = calculated_records_hash
    # The envelope digest excludes itself, avoiding a recursive hash.
    normalized.pop("result_sha256", None)
    calculated_result_hash = sha256_json(normalized)
    supplied_result_hash = value.get("result_sha256")
    if supplied_result_hash is not None:
        _digest(supplied_result_hash, "result.result_sha256")
        if supplied_result_hash.lower() != calculated_result_hash:
            raise ContractError("result.result_sha256 does not match result")
    normalized["result_sha256"] = calculated_result_hash
    return normalized


def is_valid_result(result: Mapping[str, Any]) -> bool:
    try:
        validate_result(result)
    except (ContractError, TypeError, ValueError):
        return False
    return True


def build_result(
    records: Sequence[Mapping[str, Any]],
    metadata: Mapping[str, Any],
    *,
    expected_count: int | None = None,
    status: str | None = None,
    dimensions: Mapping[str, Any] | None = None,
    summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build, validate, and hash a reproducible result envelope."""

    metadata_value = validate_metadata(metadata)
    envelope: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": metadata_value["run_id"],
        "status": status,
        "metadata": metadata_value,
        "dimensions": dimensions if dimensions is not None else metadata_value["dimensions"],
        "records": list(records),
    }
    if expected_count is not None:
        envelope["expected_count"] = expected_count
    if summary is not None:
        envelope["summary"] = dict(summary)
    return validate_result(envelope)


@dataclass(frozen=True)
class ReproducibilityMetadata:
    """Typed convenience wrapper for the required metadata fields."""

    run_id: str
    dataset_hash: str
    code_version: str
    generated_at_utc: str
    seed: int
    dimensions: Mapping[str, Any]
    dataset_name: str = "benchmark-v2"
    dataset_version: str = "1"
    extra: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = {
            **dict(self.extra),
            "run_id": self.run_id,
            "dataset": {
                "name": self.dataset_name,
                "version": self.dataset_version,
                "sha256": self.dataset_hash,
            },
            "code": {"commit": self.code_version},
            "generated_at_utc": self.generated_at_utc,
            "seed": self.seed,
            "dimensions": dict(self.dimensions),
        }
        return validate_metadata(value)


def build_metadata(
    *,
    run_id: str,
    dataset_hash: str,
    code_version: str,
    generated_at_utc: str,
    seed: int,
    dimensions: Mapping[str, Any],
    dataset_name: str = "benchmark-v2",
    dataset_version: str = "1",
    **extra: Any,
) -> dict[str, Any]:
    """Build and validate the canonical nested metadata mapping."""

    return ReproducibilityMetadata(
        run_id=run_id,
        dataset_hash=dataset_hash,
        code_version=code_version,
        generated_at_utc=generated_at_utc,
        seed=seed,
        dimensions=dimensions,
        dataset_name=dataset_name,
        dataset_version=dataset_version,
        extra=extra,
    ).to_dict()


RunMetadata = ReproducibilityMetadata
ResultMetadata = ReproducibilityMetadata
Metadata = ReproducibilityMetadata


@dataclass(frozen=True)
class BenchmarkResult:
    """Typed convenience wrapper around the canonical result envelope."""

    records: Sequence[Mapping[str, Any]]
    metadata: Mapping[str, Any]
    expected_count: int | None = None
    status: str | None = None
    dimensions: Mapping[str, Any] | None = None
    summary: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return build_result(
            self.records,
            self.metadata,
            expected_count=self.expected_count,
            status=self.status,
            dimensions=self.dimensions,
            summary=self.summary,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BenchmarkResult":
        normalized = validate_result(value)
        return cls(
            records=normalized["records"],
            metadata=normalized["metadata"],
            expected_count=normalized.get("expected_count"),
            status=normalized["status"],
            dimensions=normalized["dimensions"],
            summary=normalized.get("summary"),
        )


ResultEnvelope = BenchmarkResult


# Friendly aliases for callers that use verb-oriented names.
validate_results = validate_result
make_result = build_result


