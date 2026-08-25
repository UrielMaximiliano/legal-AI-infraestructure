"""Input contract and deterministic text normalization for semantic metrics.

The canonical case shape is ``{"case_id": str, "candidate": str,
"references": [str, ...]}``.  A missing or invalid reference is a contract
condition, not a zero score: callers receive ``NOT_CALCULABLE`` and a reason.
"""

from __future__ import annotations

from dataclasses import dataclass
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any


NOT_CALCULABLE = "NOT_CALCULABLE"
CALCULATED = "CALCULATED"
NORMALIZATION_NAME = "unicode-nfkc-casefold-whitespace"
NORMALIZATION_VERSION = "v1"


class CaseContractError(ValueError):
    """Raised when a semantic case cannot satisfy the input contract."""


def normalize_text(value: str) -> str:
    """Normalize text without removing legal punctuation or accents.

    NFKC makes compatibility forms deterministic, ``casefold`` gives
    case-insensitive lexical metrics, and ``split``/``join`` collapses all
    Unicode whitespace.  Punctuation and accents are intentionally retained:
    removing them could erase legally meaningful tokens such as ``no`` or
    article numbers.
    """

    if not isinstance(value, str):
        raise TypeError("semantic text must be a string")
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _first_present(value: Mapping[str, Any], names: Sequence[str]) -> Any:
    for name in names:
        if name in value:
            return value[name]
    return None


@dataclass(frozen=True, slots=True)
class SemanticCase:
    """A candidate answer and one or more explicit reference answers."""

    case_id: str
    candidate: str
    references: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.case_id, str) or not self.case_id.strip():
            raise CaseContractError("case_id must be a non-empty string")
        if not isinstance(self.candidate, str):
            raise CaseContractError("candidate must be a string")
        if not self.references:
            raise CaseContractError("at least one reference is required")
        if not all(isinstance(reference, str) for reference in self.references):
            raise CaseContractError("references must contain only strings")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SemanticCase":
        """Parse the canonical mapping, accepting documented input aliases."""

        if not isinstance(value, Mapping):
            raise CaseContractError("case must be a mapping")

        case_id = value.get("case_id")
        if not isinstance(case_id, str) or not case_id.strip():
            raise CaseContractError("case_id must be a non-empty string")

        candidate = _first_present(value, ("candidate", "response", "answer"))
        if not isinstance(candidate, str):
            raise CaseContractError("candidate must be a string")

        raw_references = _first_present(value, ("references", "reference", "gold"))
        if raw_references is None:
            raise CaseContractError("references are required")
        if isinstance(raw_references, str):
            references = (raw_references,)
        elif isinstance(raw_references, Sequence) and not isinstance(
            raw_references, (bytes, bytearray)
        ):
            references = tuple(raw_references)
        else:
            raise CaseContractError(
                "references must be a string or sequence of strings"
            )
        if not references:
            raise CaseContractError("at least one reference is required")
        if not all(isinstance(reference, str) for reference in references):
            raise CaseContractError("references must contain only strings")

        return cls(case_id=case_id.strip(), candidate=candidate, references=references)


def parse_case(value: SemanticCase | Mapping[str, Any]) -> SemanticCase:
    """Return a validated case without coercing missing data into text."""

    if isinstance(value, SemanticCase):
        return value
    return SemanticCase.from_mapping(value)


def normalization_metadata() -> dict[str, str]:
    """Return the versioned normalization declaration for result records."""

    return {"name": NORMALIZATION_NAME, "version": NORMALIZATION_VERSION}
