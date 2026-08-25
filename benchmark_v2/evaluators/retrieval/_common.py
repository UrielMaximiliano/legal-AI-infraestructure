"""Small, dependency-free helpers shared by retrieval evaluators."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, is_dataclass
from typing import Any


class RetrievalContractError(ValueError):
    """Raised when an evaluation input cannot be interpreted safely."""


def as_mapping(value: Any) -> Mapping[str, Any]:
    """Return a record as a mapping, accepting simple dataclass/object records."""

    if isinstance(value, Mapping):
        return value
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if hasattr(value, "__dict__"):
        return vars(value)
    raise RetrievalContractError(f"record must be a mapping, got {type(value).__name__}")


def field(value: Any, *names: str, default: Any = None) -> Any:
    """Read the first present field from a mapping or object record."""

    if isinstance(value, Mapping):
        for name in names:
            if name in value:
                return value[name]
        return default
    for name in names:
        if hasattr(value, name):
            return getattr(value, name)
    return default


def text(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def identifier(value: Any) -> str | None:
    raw = field(value, "chunk_id", "result_id", "document_chunk_id", "id")
    if raw is None or not str(raw).strip():
        return None
    return str(raw)


def query_identifier(value: Any, position: int | None = None) -> str:
    raw = field(value, "query_id", "case_id", "record_id", "id")
    if raw is None or not str(raw).strip():
        return f"query-{position}" if position is not None else "query-unknown"
    return str(raw)


def records(value: Any, *, names: Sequence[str] = ("records", "results", "cases")) -> list[Any]:
    if isinstance(value, Mapping):
        found = False
        for name in names:
            if name in value:
                value = value[name]
                found = True
                break
        if not found:
            raise RetrievalContractError("mapping does not contain a records field")
    if value is None or isinstance(value, (str, bytes, bytearray)):
        raise RetrievalContractError("records must be an iterable of cases")
    if isinstance(value, Sequence):
        return list(value)
    if isinstance(value, Iterable):
        return list(value)
    raise RetrievalContractError("records must be an iterable of cases")


def ranked_ids(value: Any) -> list[str]:
    """Extract stable, de-duplicated ranking IDs from IDs or result records."""

    items = records(value, names=("retrieved", "results", "chunks", "candidates")) if isinstance(value, Mapping) else list(value)
    indexed: list[tuple[int, int, Any]] = []
    for position, item in enumerate(items):
        rank = field(item, "rank", "retrieval_rank", default=None)
        try:
            rank_value = int(rank) if rank is not None else position + 1
        except (TypeError, ValueError):
            rank_value = position + 1
        indexed.append((rank_value, position, item))
    indexed.sort(key=lambda entry: (entry[0], entry[1]))
    result: list[str] = []
    seen: set[str] = set()
    for _, _, item in indexed:
        value_id = str(item) if isinstance(item, (str, int)) else identifier(item)
        if value_id is not None and value_id not in seen:
            result.append(value_id)
            seen.add(value_id)
    return result


def relevance_map(value: Any) -> dict[str, float]:
    """Normalise binary IDs or graded qrels to a positive gain mapping."""

    if value is None:
        return {}
    if isinstance(value, Mapping):
        # A qrels object is commonly wrapped as {"chunk_id": relevance}.
        nested = next((value[key] for key in ("relevance", "qrels", "relevant", "gold") if key in value), None)
        if nested is not None and isinstance(nested, (Mapping, Sequence, set, frozenset)):
            return relevance_map(nested)
        result: dict[str, float] = {}
        for key, gain in value.items():
            try:
                number = float(gain)
            except (TypeError, ValueError):
                number = 1.0 if bool(gain) else 0.0
            if number > 0:
                result[str(key)] = number
        return result
    if isinstance(value, (str, int)):
        return {str(value): 1.0}
    try:
        return {str(item): 1.0 for item in value if str(item).strip()}
    except TypeError as exc:
        raise RetrievalContractError("relevance must be IDs or a mapping of IDs to gains") from exc


def case_retrieved(value: Any) -> Any:
    return field(value, "retrieved", "results", "chunks", "candidates", "retrieved_chunks", default=[])


def case_relevance(value: Any) -> Any:
    return field(value, "relevance", "qrels", "relevant", "gold", "relevant_chunk_ids", default=None)


def finite_number(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return number == number and number not in {float("inf"), float("-inf")}
