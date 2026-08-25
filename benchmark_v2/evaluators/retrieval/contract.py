"""Canonical case shape and status constants for retrieval evaluation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ._common import RetrievalContractError, case_relevance, case_retrieved, query_identifier, ranked_ids, relevance_map


CALCULATED = "CALCULATED"
NOT_CALCULABLE = "NOT_CALCULABLE"
FULL = "FULL"
PARTIAL = "PARTIAL"


@dataclass(frozen=True, slots=True)
class RetrievalCase:
    """A query, an ordered result list and explicit relevance labels."""

    query_id: str
    returned_ids: tuple[str, ...]
    relevant_ids: frozenset[str]
    graded_relevance: Mapping[str, float] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.query_id, str) or not self.query_id.strip():
            raise RetrievalContractError("query_id must be a non-empty string")
        if not isinstance(self.returned_ids, tuple):
            raise RetrievalContractError("returned_ids must be a tuple")
        if not isinstance(self.relevant_ids, frozenset):
            raise RetrievalContractError("relevant_ids must be a frozenset")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RetrievalCase":
        if not isinstance(value, Mapping):
            raise RetrievalContractError("retrieval case must be a mapping")
        query_id = query_identifier(value)
        returned = ranked_ids(case_retrieved(value))
        graded = relevance_map(case_relevance(value))
        return cls(
            query_id=query_id,
            returned_ids=tuple(returned),
            relevant_ids=frozenset(graded),
            graded_relevance=graded or None,
        )

    def to_dict(self) -> dict[str, Any]:
        relevance: Any = self.graded_relevance if self.graded_relevance is not None else list(self.relevant_ids)
        return {
            "query_id": self.query_id,
            "returned_ids": list(self.returned_ids),
            "relevant_ids": sorted(self.relevant_ids),
            "relevance": relevance,
        }


EvaluationCase = RetrievalCase


def parse_case(value: RetrievalCase | Mapping[str, Any]) -> RetrievalCase:
    if isinstance(value, RetrievalCase):
        return value
    return RetrievalCase.from_mapping(value)
