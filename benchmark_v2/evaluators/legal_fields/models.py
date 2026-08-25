"""Public data types for legal-field scoring.

The evaluator intentionally keeps the wire format made of plain dictionaries,
but these small dataclasses make custom field definitions and individual field
results convenient for Python callers.  They do not depend on the application
code; this package is a benchmark-only adapter.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

# Statuses are strings rather than enums in the result envelope so that the
# output can be serialised directly to JSON and consumed by other runners.
NOT_CALCULABLE = "NOT_CALCULABLE"
NOT_APPLICABLE = "NOT_APPLICABLE"
MISSING = "MISSING"
INVALID = "INVALID"
CORRECT = "CORRECT"
INCORRECT = "INCORRECT"
PARTIAL = "PARTIAL"

# Synonyms for callers that describe a full match as exact/OK/match.  The
# serialised status remains the canonical ``CORRECT`` value.
EXACT = CORRECT
MATCH = CORRECT
OK = CORRECT


Normalizer = Callable[[Any], Any]
Validator = Callable[[Any], bool | Any]
Comparator = Callable[[Any, Any], bool | float]


@dataclass(frozen=True)
class FieldSpec:
    """Configuration for a required or user-defined legal field.

    ``expected`` is deliberately not part of this object.  Gold values belong
    to each case, while a spec describes how that value is interpreted across
    cases.  ``normalizer`` may return any hashable or JSON-like canonical value;
    ``validator`` can return a boolean or a normalised replacement value.
    """

    name: str
    normalizer: Normalizer | None = None
    validator: Validator | None = None
    comparator: Comparator | None = None
    aliases: Sequence[str] = field(default_factory=tuple)
    applicable: bool | None = None
    required: bool = True
    kind: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FieldScore:
    """A JSON-friendly score for one field."""

    field: str
    status: str
    score: float | None
    accuracy: float | None
    coverage: float | None
    applicable: bool
    expected_present: bool
    predicted_present: bool
    missing: bool = False
    invalid: bool = False
    not_applicable: bool = False
    not_calculable: bool = False
    exact: bool | None = None
    expected: Any = None
    predicted: Any = None
    precision: float | None = None
    recall: float | None = None
    f1: float | None = None
    tp: int | None = None
    fp: int | None = None
    fn: int | None = None
    reason: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return the stable result representation used by the evaluator."""

        result: dict[str, Any] = {
            "field": self.field,
            "status": self.status,
            "score": self.score,
            "accuracy": self.accuracy,
            "exactness": self.accuracy,
            "coverage": self.coverage,
            "applicable": self.applicable,
            "expected_present": self.expected_present,
            "predicted_present": self.predicted_present,
            "missing": self.missing,
            "invalid": self.invalid,
            "not_applicable": self.not_applicable,
            "not_calculable": self.not_calculable,
            "exact": self.exact,
            "expected": self.expected,
            "predicted": self.predicted,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "reason": self.reason,
        }
        result.update(self.details)
        return result


__all__ = [
    "CORRECT",
    "EXACT",
    "INCORRECT",
    "INVALID",
    "MATCH",
    "MISSING",
    "NOT_APPLICABLE",
    "NOT_CALCULABLE",
    "OK",
    "PARTIAL",
    "Comparator",
    "FieldScore",
    "FieldSpec",
    "Normalizer",
    "Validator",
]
