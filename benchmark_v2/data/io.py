"""Small, dependency-light readers and writers for benchmark datasets.

JSONL and CSV are always available.  Parquet is supported when either
``pyarrow`` or ``pandas`` with a parquet engine is installed, but importing this
module never imports either optional dependency.  Metadata is kept in a
deterministic sidecar file so a data file remains valid for ordinary tools.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
from collections.abc import Iterable, Iterator, Mapping, Sequence
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, TypeAlias

from .hashing import canonical_json, hash_metadata, sha256_file


Record: TypeAlias = Mapping[str, Any]
PathLike: TypeAlias = str | os.PathLike[str]
SUPPORTED_FORMATS = frozenset({"jsonl", "csv", "parquet"})
METADATA_SUFFIX = ".metadata.json"


class OptionalDependencyError(ImportError):
    """Raised when a requested optional storage format is unavailable."""


def _as_path(value: PathLike) -> Path:
    return Path(value)


def _format_for(path: PathLike, format: str | None = None) -> str:
    value = (format or Path(path).suffix.lstrip(".")).lower()
    if value == "ndjson":
        value = "jsonl"
    if value not in SUPPORTED_FORMATS:
        raise ValueError(
            f"unsupported data format {value!r}; expected one of "
            f"{', '.join(sorted(SUPPORTED_FORMATS))}"
        )
    return value


def metadata_path(path: PathLike) -> Path:
    """Return the sidecar path used for reproducibility metadata."""

    return Path(f"{Path(path)}{METADATA_SUFFIX}")


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as handle:
            temporary = handle.name
            handle.write(data)
        os.replace(temporary, path)
    finally:
        if temporary is not None and Path(temporary).exists():
            Path(temporary).unlink()


def _json_value(value: Any) -> Any:
    """Make a CSV cell safe while retaining nested JSON values."""

    if isinstance(value, (dict, list, tuple, set, frozenset)):
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    return "" if value is None else value


def iter_jsonl(path: PathLike) -> Iterator[dict[str, Any]]:
    """Yield JSON objects from a UTF-8 JSON Lines file."""

    with _as_path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}: invalid JSON on line {line_number}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"{path}: line {line_number} must contain a JSON object")
            yield value


def read_jsonl(path: PathLike) -> list[dict[str, Any]]:
    return list(iter_jsonl(path))


def write_jsonl(
    path: PathLike,
    records: Iterable[Record],
    *,
    metadata: Mapping[str, Any] | None = None,
) -> Path:
    """Write records as deterministic UTF-8 JSONL and return ``path``."""

    lines = []
    for record in records:
        if not isinstance(record, Mapping):
            raise TypeError("JSONL records must be mappings")
        lines.append(canonical_json(dict(record)) + b"\n")
    destination = _as_path(path)
    _atomic_write(destination, b"".join(lines))
    if metadata is not None:
        write_metadata(destination, metadata)
    return destination


def read_csv(path: PathLike) -> list[dict[str, str]]:
    """Read a CSV file as dictionaries, preserving cell text exactly."""

    with _as_path(path).open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_csv(
    path: PathLike,
    records: Iterable[Record],
    *,
    fieldnames: Sequence[str] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> Path:
    """Write records as deterministic CSV and return ``path``.

    If ``fieldnames`` is omitted, the union of all keys is sorted.  Sorting
    avoids a hash-changing header when records originate from different input
    producers.
    """

    rows = [dict(record) for record in records]
    if any(not isinstance(record, Mapping) for record in rows):
        raise TypeError("CSV records must be mappings")
    names = list(fieldnames) if fieldnames is not None else sorted(
        {str(key) for row in rows for key in row}
    )
    if len(names) != len(set(names)):
        raise ValueError("CSV fieldnames must be unique")
    output = []
    # newline="" is important for Windows CSV reproducibility.
    import io

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=names,
        extrasaction="raise",
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows({name: _json_value(row.get(name)) for name in names} for row in rows)
    output.append(buffer.getvalue().encode("utf-8"))
    destination = _as_path(path)
    _atomic_write(destination, b"".join(output))
    if metadata is not None:
        write_metadata(destination, metadata)
    return destination


def _parquet_engine() -> tuple[str, Any]:
    try:
        import pyarrow as pa  # type: ignore[import-not-found]
        import pyarrow.parquet as pq  # type: ignore[import-not-found]

        return "pyarrow", (pa, pq)
    except ImportError:
        try:
            import pandas as pd  # type: ignore[import-not-found]

            return "pandas", pd
        except ImportError as exc:
            raise OptionalDependencyError(
                "Parquet support requires optional 'pyarrow' or 'pandas' "
                "with a parquet engine; JSONL/CSV need no extra dependency"
            ) from exc


def read_parquet(path: PathLike) -> list[dict[str, Any]]:
    engine, module = _parquet_engine()
    if engine == "pyarrow":
        table = module[1].read_table(_as_path(path))
        return table.to_pylist()
    frame = module.read_parquet(_as_path(path))
    return frame.to_dict(orient="records")


def write_parquet(
    path: PathLike,
    records: Iterable[Record],
    *,
    metadata: Mapping[str, Any] | None = None,
) -> Path:
    rows = [dict(record) for record in records]
    engine, module = _parquet_engine()
    destination = _as_path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if engine == "pyarrow":
        table = module[0].Table.from_pylist(rows)
        module[1].write_table(table, destination)
    else:
        module.DataFrame(rows).to_parquet(destination, index=False)
    if metadata is not None:
        write_metadata(destination, metadata)
    return destination


def read_records(path: PathLike, *, format: str | None = None) -> list[dict[str, Any]]:
    """Read JSONL, CSV, or optional Parquet based on suffix or ``format``."""

    destination = _as_path(path)
    kind = _format_for(destination, format)
    if kind == "jsonl":
        return read_jsonl(destination)
    if kind == "csv":
        return read_csv(destination)
    return read_parquet(destination)


def write_records(
    path: PathLike,
    records: Iterable[Record],
    *,
    format: str | None = None,
    fieldnames: Sequence[str] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> Path:
    """Write records in a supported format without requiring optional packages."""

    destination = _as_path(path)
    kind = _format_for(destination, format)
    if kind == "jsonl":
        return write_jsonl(destination, records, metadata=metadata)
    if kind == "csv":
        return write_csv(destination, records, fieldnames=fieldnames, metadata=metadata)
    return write_parquet(destination, records, metadata=metadata)


def write_metadata(path: PathLike, metadata: Mapping[str, Any]) -> Path:
    """Write canonical metadata and its own digest to a sidecar file."""

    if not isinstance(metadata, Mapping):
        raise TypeError("metadata must be a mapping")
    value = dict(metadata)
    envelope = {
        "metadata": value,
        "metadata_sha256": hash_metadata(value),
    }
    destination = metadata_path(path)
    _atomic_write(destination, canonical_json(envelope) + b"\n")
    return destination


def read_metadata(path: PathLike) -> dict[str, Any]:
    """Read and verify a metadata sidecar."""

    sidecar = metadata_path(path)
    try:
        value = json.loads(sidecar.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(value, dict) or not isinstance(value.get("metadata"), dict):
        raise ValueError(f"{sidecar}: invalid metadata envelope")
    metadata = value["metadata"]
    expected = hash_metadata(metadata)
    if value.get("metadata_sha256") != expected:
        raise ValueError(f"{sidecar}: metadata hash mismatch")
    return metadata


def dataset_info(path: PathLike, *, metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return reproducibility metadata for a stored data artifact."""

    destination = _as_path(path)
    value = dict(metadata) if metadata is not None else read_metadata(destination)
    return {
        "path": destination.as_posix(),
        "format": _format_for(destination),
        "rows_sha256": sha256_file(destination),
        "metadata_sha256": hash_metadata(value) if value else None,
        "row_count": len(read_records(destination)),
        "metadata": value,
    }


def cache_path(path: PathLike, cache_dir: PathLike, *, format: str | None = None) -> Path:
    """Return the content-addressed cache path for ``path``."""

    source = _as_path(path)
    kind = _format_for(source, format)
    return _as_path(cache_dir) / f"{sha256_file(source)}.{kind}"


def cache_records(
    path: PathLike,
    cache_dir: PathLike,
    *,
    format: str | None = None,
) -> Path:
    """Copy a data artifact into a content-addressed cache and return its path."""

    source = _as_path(path)
    destination = cache_path(source, cache_dir, format=format)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        shutil.copyfile(source, destination)
    sidecar = metadata_path(source)
    if sidecar.exists() and not metadata_path(destination).exists():
        shutil.copyfile(sidecar, metadata_path(destination))
    return destination


def read_cached(
    path: PathLike,
    cache_dir: PathLike,
    *,
    format: str | None = None,
) -> list[dict[str, Any]]:
    """Populate/read the content-addressed cache for ``path``."""

    return read_records(cache_records(path, cache_dir, format=format), format=format)


class HashCache:
    """A minimal content-addressed file cache for benchmark artifacts."""

    def __init__(self, directory: PathLike):
        self.directory = _as_path(directory)

    def key_for(self, path: PathLike) -> str:
        return sha256_file(path)

    def path_for(self, path: PathLike, *, format: str | None = None) -> Path:
        return cache_path(path, self.directory, format=format)

    def put(self, path: PathLike, *, format: str | None = None) -> Path:
        return cache_records(path, self.directory, format=format)

    def get(self, path: PathLike, *, format: str | None = None) -> Path | None:
        destination = self.path_for(path, format=format)
        return destination if destination.exists() else None

    def get_records(self, path: PathLike, *, format: str | None = None) -> list[dict[str, Any]]:
        return read_cached(path, self.directory, format=format)


# Common aliases used by small benchmark scripts.
load_records = read_records
save_records = write_records
read_table = read_records
write_table = write_records
load_jsonl = read_jsonl
save_jsonl = write_jsonl
load_csv = read_csv
save_csv = write_csv
load_parquet = read_parquet
save_parquet = write_parquet
load_dataset = read_records
save_dataset = write_records


