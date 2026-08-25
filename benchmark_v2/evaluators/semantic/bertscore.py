"""Optional BERTScore adapter with explicit dependency degradation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .contract import CALCULATED, NOT_CALCULABLE, normalize_text


@dataclass(frozen=True, slots=True)
class BERTScoreConfig:
    """Configuration passed to ``bert_score.score``.

    A fixed multilingual encoder and Spanish language flag make the default
    protocol explicit.  Users comparing runs should still record the package
    version and model revision in their run metadata.
    """

    model_type: str = "bert-base-multilingual-cased"
    lang: str = "es"
    idf: bool = False
    rescale_with_baseline: bool = False
    device: str | None = None
    batch_size: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_type": self.model_type,
            "lang": self.lang,
            "idf": self.idf,
            "rescale_with_baseline": self.rescale_with_baseline,
            "device": self.device,
            "batch_size": self.batch_size,
        }


def _scalar(value: Any) -> float:
    """Convert a one-item tensor/list/NumPy value without importing NumPy."""

    if hasattr(value, "item"):
        value = value.item()
    elif isinstance(value, (list, tuple)):
        if len(value) != 1:
            raise ValueError("expected one BERTScore value")
        return _scalar(value[0])
    return float(value)


class BERTScoreEvaluator:
    """Lazy adapter around the optional :mod:`bert_score` package.

    Instantiation never downloads a model.  If the package is unavailable, or
    scoring fails, ``score`` returns a NOT_CALCULABLE record and no fabricated
    numeric value.  ``score_fn`` is injectable for deterministic unit tests.
    """

    name = "bertscore"

    def __init__(
        self,
        config: BERTScoreConfig | None = None,
        *,
        score_fn: Callable[..., Any] | None = None,
    ) -> None:
        self.config = config or BERTScoreConfig()
        self._score_fn = score_fn
        self._load_error: Exception | None = None

    @property
    def available(self) -> bool:
        return self._get_score_fn() is not None

    def _get_score_fn(self) -> Callable[..., Any] | None:
        if self._score_fn is not None:
            return self._score_fn
        try:
            from bert_score import score as score_fn
        except Exception as exc:
            self._load_error = exc
            return None
        self._score_fn = score_fn
        return score_fn

    def _not_calculable(self, reason: str) -> dict[str, Any]:
        return {
            "status": NOT_CALCULABLE,
            "score": None,
            "precision": None,
            "recall": None,
            "f1": None,
            "reason": reason,
            "dependency": "bert-score",
            "config": self.config.to_dict(),
        }

    def score(self, candidate: str, reference: str) -> dict[str, Any]:
        """Score one normalized candidate/reference pair."""

        score_fn = self._get_score_fn()
        if score_fn is None:
            return self._not_calculable("optional_dependency_missing:bert-score")

        kwargs: dict[str, Any] = {
            "model_type": self.config.model_type,
            "lang": self.config.lang,
            "idf": self.config.idf,
            "rescale_with_baseline": self.config.rescale_with_baseline,
            "verbose": False,
        }
        if self.config.device is not None:
            kwargs["device"] = self.config.device
        if self.config.batch_size is not None:
            kwargs["batch_size"] = self.config.batch_size

        try:
            precision, recall, f1 = score_fn(
                [normalize_text(candidate)], [normalize_text(reference)], **kwargs
            )
            values = {
                "status": CALCULATED,
                "score": _scalar(f1),
                "precision": _scalar(precision),
                "recall": _scalar(recall),
                "f1": _scalar(f1),
                "reason": None,
                "dependency": "bert-score",
                "config": self.config.to_dict(),
            }
        except Exception as exc:  # optional backend errors are explicit data
            values = self._not_calculable(f"backend_error:{type(exc).__name__}")
        return values
