"""In-process metrics sink for corpus tests and local operation."""

from __future__ import annotations

from collections import Counter


class CorpusMetrics:
    def __init__(self) -> None:
        self._counts: Counter[tuple[str, tuple[tuple[str, str], ...]]] = Counter()

    def increment(
        self,
        name: str,
        *,
        value: int = 1,
        tags: dict[str, str] | None = None,
    ) -> None:
        if not name or value < 0:
            raise ValueError("CORPUS_METRIC_INVALID")
        normalized_tags = tuple(sorted((tags or {}).items()))
        self._counts[(name, normalized_tags)] += value

    def get(self, name: str, *, tags: dict[str, str] | None = None) -> int:
        return self._counts[(name, tuple(sorted((tags or {}).items())))]

    def snapshot(self) -> dict[str, int]:
        return {
            name: sum(
                value for (metric, _), value in self._counts.items() if metric == name
            )
            for name in {metric for metric, _ in self._counts}
        }
