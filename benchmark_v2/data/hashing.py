"""Deterministic hashing helpers used by the benchmark-v2 data contract.

The benchmark deliberately hashes *representations*, rather than Python object
identity.  This makes cache keys and manifests stable across processes and
machines (and means that a dictionary's insertion order cannot change a run
identifier).  The module only uses the standard library.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from datetime import date, datetime, time, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterator


HASH_ALGORITHM = "sha256"
DEFAULT_CHUNK_SIZE = 1024 * 1024


def _normalise(value: Any) -> Any:
    """Convert common Python values to a canonical JSON-compatible value."""

    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _normalise(dataclasses.asdict(value))
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, Enum):
        return _normalise(value.value)
    if isinstance(value, datetime):
        # A timezone-naive timestamp is retained as-is: silently assuming a
        # timezone would make a manifest look reproducible while changing its
        # meaning.  Aware UTC timestamps get a single, canonical spelling.
        if value.tzinfo is not None and value.utcoffset() == timezone.utc.utcoffset(value):
            return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        return value.isoformat()
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite floats are not supported in hashed data")
        return value
    if isinstance(value, dict):
        return {
            str(key): _normalise(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (set, frozenset)):
        items = [_normalise(item) for item in value]
        return sorted(items, key=_canonical_sort_key)
    if isinstance(value, (list, tuple)):
        return [_normalise(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    # Let JSON provide a useful error for unsupported values, but make the
    # failure deterministic and explicit for custom objects.
    raise TypeError(f"unsupported value for canonical hashing: {type(value)!r}")


def _canonical_sort_key(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonicalize(value: Any) -> Any:
    """Return a JSON-compatible canonical representation of ``value``."""

    return _normalise(value)


def canonical_json(value: Any) -> bytes:
    """Serialise ``value`` deterministically as UTF-8 JSON bytes."""

    return json.dumps(
        canonicalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(data: bytes | bytearray | memoryview) -> str:
    """Return the lowercase SHA-256 digest for bytes-like ``data``."""

    return hashlib.sha256(bytes(data)).hexdigest()


def sha256_text(value: str) -> str:
    """Return the SHA-256 digest of UTF-8 encoded text."""

    return sha256_bytes(value.encode("utf-8"))


def sha256_file(path: str | Path, *, chunk_size: int = DEFAULT_CHUNK_SIZE) -> str:
    """Hash a file without loading it all into memory."""

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    """Hash a canonical JSON representation of ``value``."""

    return sha256_bytes(canonical_json(value))


def hash_records(records: Any) -> str:
    """Hash an iterable of records in its supplied order.

    Record order is meaningful for JSONL/CSV datasets, so callers that want an
    order-independent digest should sort records explicitly (usually by a
    stable case identifier) before calling this function.
    """

    return sha256_json(list(records))


def hash_metadata(metadata: Any) -> str:
    """Return a stable digest for reproducibility metadata."""

    return sha256_json(metadata)


def cache_key(*parts: Any, namespace: str = "benchmark-v2") -> str:
    """Build a collision-resistant, deterministic cache key.

    The namespace is part of the hashed envelope, so callers can safely reuse
    the same cache directory for unrelated artifact types.
    """

    return sha256_json({"namespace": namespace, "parts": list(parts)})


def artifact_hash(value: Any) -> str:
    """Backward-compatible alias for hashing a JSON-compatible artifact."""

    if isinstance(value, (bytes, bytearray, memoryview)):
        return sha256_bytes(value)
    if isinstance(value, (str, Path)):
        candidate = Path(value)
        if isinstance(value, Path) or candidate.is_file():
            return sha256_file(candidate)
        return sha256_text(str(value))
    return sha256_json(value)


# Short aliases are intentionally public: they make the contract convenient in
# notebooks without forcing users to remember whether they are hashing text,
# JSON, or a file.
hash_file = sha256_file
hash_json = sha256_json
hash_text = sha256_text
stable_hash = sha256_json
sha256_digest = sha256_bytes


