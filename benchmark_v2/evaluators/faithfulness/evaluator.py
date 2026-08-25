"""Claim-level faithfulness and groundedness evaluation.

The evaluator intentionally has a small, dependency-free core.  It evaluates
only an answer against traceable RAG evidence; a list of citations or
``references`` attached to an answer is not evidence and is never consulted.
An entailment function can be supplied by callers that have a model-backed
entailment service.  The default lexical scorer is useful for deterministic
unit tests and for environments where optional model dependencies are absent.
"""

from __future__ import annotations

import inspect
import math
import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any


STATUS_CALCULATED = "CALCULATED"
STATUS_NOT_CALCULABLE = "NOT_CALCULABLE"
CLAIM_SUPPORTED = "SUPPORTED"
CLAIM_UNSUPPORTED = "UNSUPPORTED"
CLAIM_NOT_CALCULABLE = STATUS_NOT_CALCULABLE

_TEXT_KEYS = ("text", "content", "passage", "snippet", "chunk_text", "page_content", "body")
_CONTAINER_KEYS = (
    "rag_context",
    "rag_trace",
    "retrieval_trace",
    "retrieval",
    "context",
    "chunks",
    "evidence",
    "documents",
    "passages",
    "items",
    "results",
    "retrieved_documents",
    "retrieved_chunks",
)
_IGNORED_CONTAINER_KEYS = frozenset(
    {"references", "filtered_references", "citations", "filtered_citations", "links"}
)
_IDENTIFIER_KEYS = (
    "evidence_id",
    "chunk_id",
    "source_id",
    "document_id",
    "doc_id",
    "source",
    "file",
    "citation_id",
    "reference_id",
    "uri",
    "url",
    "id",
)
_TRACE_KEYS = ("trace_id", "retrieval_id", "query_id", "request_id", "run_id")
_FILTER_KEYS = (
    "filtered",
    "is_filtered",
    "filter_status",
    "excluded",
    "is_excluded",
    "selected",
    "is_selected",
    "ranked_out",
)
_STOPWORDS = frozenset(
    {
        "a",
        "al",
        "ante",
        "con",
        "contra",
        "de",
        "del",
        "desde",
        "durante",
        "e",
        "el",
        "ella",
        "ellas",
        "ellos",
        "en",
        "entre",
        "es",
        "esta",
        "este",
        "estos",
        "la",
        "las",
        "lo",
        "los",
        "of",
        "on",
        "or",
        "para",
        "por",
        "que",
        "se",
        "segun",
        "sin",
        "su",
        "sus",
        "the",
        "to",
        "un",
        "una",
        "y",
        "and",
    }
)

EntailmentFunction = Callable[[str, str], Any]


def _normalise_text(value: Any) -> str:
    """Return text from a scalar without treating metadata as evidence."""

    if not isinstance(value, str):
        return ""
    value = unicodedata.normalize("NFKC", value).replace("\x00", " ")
    return re.sub(r"\s+", " ", value).strip()


def _tokens(value: str) -> list[str]:
    normalised = unicodedata.normalize("NFKD", value or "")
    normalised = "".join(char for char in normalised if not unicodedata.combining(char))
    words = re.findall(r"[\w]+", normalised.lower(), flags=re.UNICODE)
    return [word for word in words if word not in _STOPWORDS]


def lexical_entailment(claim: str, evidence: str) -> float:
    """Return deterministic token recall of *claim* in *evidence*.

    This is deliberately a recall-like proxy, not a claim of semantic truth.
    Production callers should provide a model or rules engine through the
    ``entailment`` configuration parameter.
    """

    claim_tokens = _tokens(claim)
    if not claim_tokens:
        return 0.0
    evidence_tokens = _tokens(evidence)
    if not evidence_tokens:
        return 0.0
    available = set(evidence_tokens)
    overlap = sum(token in available for token in claim_tokens)
    return overlap / len(claim_tokens)


@dataclass(frozen=True)
class Evidence:
    """A single traceable RAG chunk used by the evaluator."""

    evidence_id: str
    text: str
    source_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    trace_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "evidence_id": self.evidence_id,
            "text": self.text,
        }
        if self.source_id is not None:
            result["source_id"] = self.source_id
        if self.trace_id is not None:
            result["trace_id"] = self.trace_id
        if self.metadata:
            result["metadata"] = dict(self.metadata)
        return result


@dataclass(frozen=True)
class EntailmentConfig:
    """Configurable entailment strategy and decision threshold."""

    entailment: Any = lexical_entailment
    threshold: float = 0.8
    name: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.threshold, (int, float)) or isinstance(self.threshold, bool):
            raise TypeError("entailment threshold must be numeric")
        if not 0.0 <= float(self.threshold) <= 1.0:
            raise ValueError("entailment threshold must be between 0 and 1")


class FaithfulnessResult(dict[str, Any]):
    """Mapping result with attribute access for interactive callers."""

    @property
    def status(self) -> str:
        return str(self["status"])

    @property
    def claims(self) -> list[dict[str, Any]]:
        return self["claims"]

    @property
    def faithfulness(self) -> float | None:
        return self.get("faithfulness")

    @property
    def groundedness(self) -> float | None:
        return self.get("groundedness")

    def to_dict(self) -> dict[str, Any]:
        return dict(self)


def _first_text(mapping: Mapping[str, Any]) -> str:
    for key in _TEXT_KEYS:
        value = mapping.get(key)
        text = _normalise_text(value)
        if text:
            return text
    return ""


def _metadata(mapping: Mapping[str, Any]) -> Mapping[str, Any]:
    value = mapping.get("metadata")
    if isinstance(value, Mapping):
        return value
    value = mapping.get("provenance")
    return value if isinstance(value, Mapping) else {}


def _field(mapping: Mapping[str, Any], keys: Iterable[str]) -> Any:
    metadata = _metadata(mapping)
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
        if key in metadata and metadata[key] not in (None, ""):
            return metadata[key]
    return None


def _filtered(mapping: Mapping[str, Any]) -> bool:
    """Identify chunks removed by retrieval/filtering without trusting them."""

    metadata = _metadata(mapping)
    values_by_key = {
        key: [mapping.get(key), metadata.get(key)] for key in _FILTER_KEYS
    }
    for key in ("selected", "is_selected"):
        for value in values_by_key[key]:
            if value is False or (
                isinstance(value, str) and value.strip().lower() in {"false", "no"}
            ):
                return True
    values = [value for values in values_by_key.values() for value in values]
    for value in values:
        if isinstance(value, str) and value.strip().lower() in {
            "filtered",
            "excluded",
            "removed",
            "ranked_out",
            "false",
            "no",
        }:
            return True
        if value is True:
            return True
        if value is False:
            continue
    kind = str(_field(mapping, ("source_type", "kind", "type")) or "").lower()
    return "filtered" in kind or "excluded" in kind


def _identifier(mapping: Mapping[str, Any]) -> tuple[str | None, str | None]:
    metadata = _metadata(mapping)
    evidence_id: str | None = None
    source_id: str | None = None
    for key in _IDENTIFIER_KEYS:
        value = mapping.get(key, metadata.get(key))
        if value in (None, ""):
            continue
        text = _normalise_text(value)
        if not text:
            continue
        if key in {"source_id", "document_id", "doc_id", "source", "file", "uri", "url"} and source_id is None:
            source_id = text
        if evidence_id is None:
            evidence_id = text
    return evidence_id, source_id


def _trace_id(mapping: Mapping[str, Any]) -> str | None:
    metadata = _metadata(mapping)
    for key in _TRACE_KEYS:
        value = mapping.get(key, metadata.get(key))
        text = _normalise_text(value)
        if text:
            return text
    return None


def _is_record(mapping: Mapping[str, Any]) -> bool:
    return bool(_first_text(mapping))


def _evidence_from_record(
    mapping: Mapping[str, Any],
    *,
    parent_trace: str | None = None,
    index: int = 0,
) -> Evidence | None:
    if _filtered(mapping):
        return None
    text = _first_text(mapping)
    if not text:
        return None
    evidence_id, source_id = _identifier(mapping)
    trace_id = _trace_id(mapping) or parent_trace
    # A trace-level identifier makes otherwise anonymous chunks auditable.
    if evidence_id is None and trace_id is not None:
        evidence_id = f"{trace_id}:chunk-{index + 1}"
    if evidence_id is None:
        return None
    return Evidence(
        evidence_id=evidence_id,
        source_id=source_id,
        text=text,
        metadata=dict(_metadata(mapping)),
        trace_id=trace_id,
    )


def _evidence_items(
    value: Any,
    *,
    parent_trace: str | None = None,
    counter: list[int] | None = None,
) -> list[Evidence]:
    """Extract only explicit RAG context containers, never references."""

    if counter is None:
        counter = [0]
    if isinstance(value, Evidence):
        return [value]
    if isinstance(value, Mapping):
        local_trace = _trace_id(value) or parent_trace
        record = _evidence_from_record(value, parent_trace=local_trace, index=counter[0])
        if record is not None:
            counter[0] += 1
            return [record]
        result: list[Evidence] = []
        # Do not recurse through references/citations: they can be a filtered
        # post-processing artifact rather than the context sent to the model.
        for key in _CONTAINER_KEYS:
            if key in _IGNORED_CONTAINER_KEYS or key not in value:
                continue
            result.extend(
                _evidence_items(value[key], parent_trace=local_trace, counter=counter)
            )
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        result = []
        for item in value:
            result.extend(_evidence_items(item, parent_trace=parent_trace, counter=counter))
        return result
    return []


def extract_evidence(context: Any) -> list[Evidence]:
    """Return de-duplicated, traceable evidence from a RAG context.

    Bare strings and top-level ``references``/``citations`` are intentionally
    rejected.  Each returned item has an origin identifier or a retrieval trace
    from which a stable chunk identifier can be derived.
    """

    result: list[Evidence] = []
    seen: set[tuple[str, str]] = set()
    for item in _evidence_items(context):
        key = (item.evidence_id, item.text)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _answer_text(answer: Any) -> str:
    if isinstance(answer, str):
        return _normalise_text(answer)
    if isinstance(answer, Mapping):
        for key in ("answer", "response", "output", "text", "content"):
            value = answer.get(key)
            if isinstance(value, str):
                return _normalise_text(value)
        return ""
    if isinstance(answer, Sequence) and not isinstance(answer, (bytes, bytearray)):
        return " ".join(_answer_text(item) for item in answer if _answer_text(item))
    return ""


def extract_claims(answer: Any, claims: Sequence[Any] | None = None) -> list[dict[str, str]]:
    """Extract atomic-ish sentence claims from an answer.

    Callers may pass explicit claims to avoid sentence segmentation.  Answer
    references/citations are never read as claims.
    """

    values: list[tuple[str | None, str]] = []
    if claims is not None:
        for index, item in enumerate(claims):
            if isinstance(item, Mapping):
                text = _first_text(item) or _normalise_text(item.get("claim"))
                claim_id = _normalise_text(item.get("claim_id") or item.get("id")) or None
            else:
                text = _normalise_text(item)
                claim_id = None
            if text:
                values.append((claim_id or f"claim-{index + 1}", text))
    elif isinstance(answer, Mapping) and isinstance(answer.get("claims"), Sequence):
        return extract_claims(answer, answer["claims"])
    else:
        text = _answer_text(answer)
        # Remove markdown citation/link syntax from a claim but not its prose.
        pieces = re.split(r"(?<=[.!?。！？])\s+|\n+|(?<=;)\s+", text)
        for piece in pieces:
            value = re.sub(r"\[[^\]]*\]\([^)]*\)", "", piece)
            value = re.sub(r"\[[0-9][0-9,;\- ]*\]", "", value)
            value = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", value)
            value = _normalise_text(value).strip(" -—–")
            if value:
                values.append((None, value))
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, (claim_id, text) in enumerate(values):
        if len(_tokens(text)) < 2:
            continue
        key = " ".join(_tokens(text))
        if key in seen:
            continue
        seen.add(key)
        result.append({"claim_id": claim_id or f"claim-{index + 1}", "claim": text})
    return result


def _call_with_compatible_signature(strategy: Any, claim: str, evidence: Evidence) -> Any:
    if hasattr(strategy, "entails"):
        target = strategy.entails
    elif hasattr(strategy, "score"):
        target = strategy.score
    elif hasattr(strategy, "evaluate"):
        target = strategy.evaluate
    elif callable(strategy):
        target = strategy
    else:
        raise TypeError("entailment must be callable or expose entails/score/evaluate")

    # The documented contract is (claim, evidence_text).  The additional
    # forms keep the evaluator convenient for small adapters that want the
    # complete evidence record or metadata.
    candidates = ((claim, evidence.text), (claim, evidence), (claim, evidence.text, evidence))
    try:
        signature = inspect.signature(target)
        positional = [
            parameter
            for parameter in signature.parameters.values()
            if parameter.kind
            in {parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD}
        ]
        if any(parameter.kind == parameter.VAR_POSITIONAL for parameter in signature.parameters.values()):
            return target(*candidates[-1])
        count = len(positional)
        if count >= 3:
            return target(*candidates[-1])
        if count == 2:
            return target(*candidates[0])
        if count == 1:
            return target(claim)
        return target()
    except (TypeError, ValueError):
        for args in candidates:
            try:
                return target(*args)
            except TypeError:
                continue
        raise


def _score_entailment(value: Any) -> float:
    if isinstance(value, Mapping):
        for key in ("score", "confidence", "entailment_score", "probability"):
            if key in value:
                return _score_entailment(value[key])
        for key in ("entailed", "entails", "supported", "is_supported"):
            if key in value:
                return 1.0 if bool(value[key]) else 0.0
        status = str(value.get("status", "")).upper()
        if status in {CLAIM_SUPPORTED, "ENTAILED", "TRUE", "YES"}:
            return 1.0
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(float(value)):
            return 0.0
        return max(0.0, min(1.0, float(value)))
    if isinstance(value, str):
        status = value.strip().upper()
        if status in {CLAIM_SUPPORTED, "ENTAILED", "TRUE", "YES"}:
            return 1.0
        try:
            return _score_entailment(float(value))
        except ValueError:
            return 0.0
    return 0.0


class FaithfulnessEvaluator:
    """Evaluate answer claims against traceable RAG evidence."""

    def __init__(
        self,
        entailment: Any = lexical_entailment,
        *,
        threshold: float = 0.8,
        entailment_name: str | None = None,
        entailment_fn: Any = None,
        config: EntailmentConfig | None = None,
    ) -> None:
        if config is not None:
            if not isinstance(config, EntailmentConfig):
                raise TypeError("config must be an EntailmentConfig")
            self.config = config
            return
        if entailment_fn is not None:
            entailment = entailment_fn
        if isinstance(entailment, EntailmentConfig):
            self.config = entailment
        else:
            self.config = EntailmentConfig(
                entailment or lexical_entailment, threshold, entailment_name
            )

    def evaluate(
        self,
        answer: Any,
        context: Any = None,
        *,
        rag_context: Any = None,
        evidence: Any = None,
        claims: Sequence[Any] | None = None,
    ) -> FaithfulnessResult:
        source = rag_context if rag_context is not None else evidence
        if source is None:
            source = context
        evidence_rows = extract_evidence(source)
        claim_rows = extract_claims(answer, claims)
        method_name = self.config.name or getattr(self.config.entailment, "__name__", "custom")
        base: dict[str, Any] = {
            "status": STATUS_NOT_CALCULABLE,
            "evaluation_status": STATUS_NOT_CALCULABLE,
            "faithfulness": None,
            "groundedness": None,
            "evidence_support": None,
            "entailment_mean": None,
            "claims_total": len(claim_rows),
            "claims_supported": 0,
            "claims_unsupported": 0,
            "claims": [],
            "claim_scores": [],
            "supported_claims": [],
            "unsupported_claims": [],
            "unsupported_claim_details": [],
            "evidence": [item.to_dict() for item in evidence_rows],
            "entailment": {"name": method_name, "threshold": float(self.config.threshold)},
            "reason": None,
        }
        if not evidence_rows:
            base["reason"] = "no_traceable_rag_context"
            base["claims"] = [
                {
                    "claim_id": item["claim_id"],
                    "claim": item["claim"],
                    "status": CLAIM_NOT_CALCULABLE,
                    "entailment_score": None,
                    "evidence_ids": [],
                    "support": [],
                    "evidence": [],
                    "reason": "no_traceable_rag_context",
                }
                for item in claim_rows
            ]
            base["claim_scores"] = base["claims"]
            return FaithfulnessResult(base)
        if not claim_rows:
            base["reason"] = "no_claims"
            base["claims"] = []
            return FaithfulnessResult(base)

        evaluated: list[dict[str, Any]] = []
        scores: list[float] = []
        supported: list[dict[str, Any]] = []
        unsupported: list[dict[str, Any]] = []
        for item in claim_rows:
            candidates: list[tuple[Evidence, float]] = []
            for row in evidence_rows:
                raw = _call_with_compatible_signature(self.config.entailment, item["claim"], row)
                score = _score_entailment(raw)
                candidates.append((row, score))
            best_score = max((score for _, score in candidates), default=0.0)
            support = [
                {"evidence_id": row.evidence_id, "score": score}
                for row, score in candidates
                if score >= float(self.config.threshold)
            ]
            evidence_ids = [entry["evidence_id"] for entry in support]
            row = {
                "claim_id": item["claim_id"],
                "claim": item["claim"],
                "status": CLAIM_SUPPORTED if support else CLAIM_UNSUPPORTED,
                "entailment_score": best_score,
                "evidence_ids": evidence_ids,
                "support": support,
                "evidence": [
                    {
                        "evidence_id": evidence_id,
                        "score": score,
                        "text": next(
                            evidence_row.text
                            for evidence_row in evidence_rows
                            if evidence_row.evidence_id == evidence_id
                        ),
                    }
                    for evidence_id, score in (
                        (entry["evidence_id"], entry["score"]) for entry in support
                    )
                ],
                "reason": None if support else "no_entailing_evidence",
            }
            evaluated.append(row)
            scores.append(best_score)
            if support:
                supported.append(row)
            else:
                unsupported.append(row)

        faithfulness = len(supported) / len(evaluated)
        groundedness = sum(scores) / len(scores)
        base.update(
            {
                "status": STATUS_CALCULATED,
                "evaluation_status": STATUS_CALCULATED,
                "faithfulness": faithfulness,
                "groundedness": groundedness,
                "evidence_support": faithfulness,
                "entailment_mean": groundedness,
                "claims_supported": len(supported),
                "claims_unsupported": len(unsupported),
                "claims": evaluated,
                "claim_scores": evaluated,
                "supported_claims": [row["claim"] for row in supported],
                "unsupported_claims": [row["claim"] for row in unsupported],
                "unsupported_claim_ids": [row["claim_id"] for row in unsupported],
                "unsupported_claim_details": unsupported,
            }
        )
        return FaithfulnessResult(base)


def evaluate_faithfulness(
    answer: Any,
    context: Any = None,
    *,
    rag_context: Any = None,
    evidence: Any = None,
    claims: Sequence[Any] | None = None,
    entailment: Any = lexical_entailment,
    threshold: float = 0.8,
    entailment_name: str | None = None,
    entailment_fn: Any = None,
    config: EntailmentConfig | None = None,
) -> FaithfulnessResult:
    """Evaluate answer faithfulness at claim granularity."""

    return FaithfulnessEvaluator(
        entailment,
        threshold=threshold,
        entailment_name=entailment_name,
        entailment_fn=entailment_fn,
        config=config,
    ).evaluate(
        answer,
        context,
        rag_context=rag_context,
        evidence=evidence,
        claims=claims,
    )


def evaluate_groundedness(*args: Any, **kwargs: Any) -> FaithfulnessResult:
    """Alias for callers that name the metric groundedness."""

    return evaluate_faithfulness(*args, **kwargs)


# Friendly aliases used by benchmark runners.
evaluate = evaluate_faithfulness
calculate_faithfulness = evaluate_faithfulness
extract_claim = extract_claims
extract_rag_evidence = extract_evidence


__all__ = [
    "CLAIM_NOT_CALCULABLE",
    "CLAIM_SUPPORTED",
    "CLAIM_UNSUPPORTED",
    "EntailmentConfig",
    "EntailmentFunction",
    "Evidence",
    "FaithfulnessEvaluator",
    "FaithfulnessResult",
    "STATUS_CALCULATED",
    "STATUS_NOT_CALCULABLE",
    "evaluate",
    "evaluate_faithfulness",
    "evaluate_groundedness",
    "calculate_faithfulness",
    "extract_claim",
    "extract_claims",
    "extract_evidence",
    "extract_rag_evidence",
    "lexical_entailment",
]
