"""Object-oriented facade for legal-field scoring."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .models import FieldSpec
from .scoring import score_legal_fields


class LegalFieldsEvaluator:
    """Reusable evaluator with a stable field configuration.

    The class is intentionally stateless between calls.  This makes it safe to
    reuse in a benchmark runner while keeping each result independent and
    deterministic.
    """

    def __init__(
        self,
        fields: Sequence[str] | Mapping[str, Any] | Sequence[FieldSpec] | None = None,
        *,
        required_fields: Sequence[str] | None = None,
        configurable_fields: Sequence[str] | Mapping[str, Any] | Sequence[FieldSpec] | None = None,
        field_config: Mapping[str, Any] | None = None,
    ) -> None:
        self.fields = fields
        self.required_fields = required_fields
        self.configurable_fields = configurable_fields
        self.field_config = field_config

    def evaluate(self, expected: Any, predicted: Any) -> dict[str, Any]:
        """Evaluate one case."""

        return score_legal_fields(
            expected,
            predicted,
            fields=self.fields,
            required_fields=self.required_fields,
            configurable_fields=self.configurable_fields,
            field_config=self.field_config,
        )

    score = evaluate

    def evaluate_case(self, reference: Any, candidate: Any) -> dict[str, Any]:
        """Evaluate a case using the common reference/candidate vocabulary."""

        return self.evaluate(reference, candidate)

    def __call__(self, expected: Any, predicted: Any) -> dict[str, Any]:
        return self.evaluate(expected, predicted)


Evaluator = LegalFieldsEvaluator
LegalFieldEvaluator = LegalFieldsEvaluator

__all__ = ["Evaluator", "LegalFieldEvaluator", "LegalFieldsEvaluator"]
