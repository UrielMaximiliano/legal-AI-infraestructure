"""Claims, legal-entity, and contradiction evaluation primitives.

This module is intentionally conservative: predictions can be extracted from
text or accepted as structured objects, but truth is *always* supplied by the
caller through ``gold``.  A missing or malformed gold dimension is
``NOT_CALCULABLE``; it is never silently inferred from the prediction.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

TP = "TP"
FP = "FP"
FN = "FN"
NOT_CALCULABLE = "NOT_CALCULABLE"
DIMENSIONS = ("claims", "entities", "contradictions")

_DIMENSION_KEYS: dict[str, tuple[str, ...]] = {
    "claims": ("claims", "atomic_claims", "facts", "gold_claims"),
    "entities": ("entities", "legal_entities", "gold_entities"),
    "contradictions": (
        "contradictions",
        "conflicts",
        "gold_contradictions",
    ),
}
_WRAPPER_KEYS = ("output", "result", "response", "record", "answer")
_NEGATION_WORDS = {
    "no",
    "nunca",
    "jamás",
    "jamas",
    "sin",
    "prohibido",
    "prohibida",
    "impide",
    "impedir",
}
_NEGATION_RE = re.compile(
    r"\b(?:no|nunca|jam[aá]s|sin|prohibid[oa]s?|impide|impedir)\b",
    re.IGNORECASE,
)
_CLAUSE_RE = re.compile(
    r"\s+(?:y|e|pero|aunque|sin\s+embargo)\s+"
    r"(?=(?:el|la|los|las|un|una|se|no|debe|deberá|debera|podrá|podra|"
    r"puede|queda|resulta|es|son)\b)",
    re.IGNORECASE,
)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|[;\n]+")
_LEGAL_INSTRUMENT_RE = re.compile(
    r"\b(?:Ley|Decreto|Resoluci[oó]n|Disposici[oó]n|Ordenanza|"
    r"Sentencia|Acordada|Decisi[oó]n\s+Administrativa)\b"
    r"(?:\s+(?:N(?:ro?\.?|[°ºo])?\s*)?)?"
    r"[A-Z0-9][A-Z0-9./:-]*(?:\s*/\s*\d{2,4})?",
    re.IGNORECASE,
)
_CASE_RE = re.compile(
    r"\b(?:Expediente|Expte\.?|Causa|Autos)\s+(?:N(?:ro?\.?|[°ºo])?\s*)?"
    r"[A-Z0-9][A-Z0-9:/._-]{2,}",
    re.IGNORECASE,
)
_COURT_RE = re.compile(
    r"\b(?:Corte|Tribunal|Juzgado|C[aá]mara|Fiscal[ií]a|Defensor[ií]a)\b"
    r"[^,.;\n]*",
    re.IGNORECASE,
)
_ORG_RE = re.compile(
    r"\b(?:Ministerio|Secretar[ií]a|Direcci[oó]n|Administraci[oó]n|"
    r"Instituto|Municipalidad|Provincia|Universidad|Banco|Estado|"
    r"Agencia|Comisi[oó]n|Defensor[ií]a|Fiscal[ií]a)\b"
    r"(?:\s+(?:de|del|la|las|los|y|[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑ'-]*)){0,9}",
)
_PERSON_RE = re.compile(
    r"\b(?:Sr\.?|Sra\.?|Dr\.?|Dra\.?|Lic\.?|Abg\.?)\s+"
    r"([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑ'-]+(?:\s+[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑ'-]+){1,3})"
)
_ACRONYM_RE = re.compile(r"\b[A-ZÁÉÍÓÚÑ]{3,}(?:\s+[A-ZÁÉÍÓÚÑ]{2,})?\b")
_VERB_RE = re.compile(
    r"\b(es|son|ser[aá]|debe|deber[aá]|podr[aá]|puede|corresponde|rige|"
    r"aplica|establece|vence|dura|tiene|incluye|proh[ií]be|autoriza|"
    r"ordena|obliga|cumple|incumple|solicita|requiere|presenta|emite|"
    r"notifica|se[nñ]ala|indica|fija|otorga|designa|nombra|recae|"
    r"consiste|deber[aá]n|podr[aá]n)\b",
    re.IGNORECASE,
)
_NOISE_ACRONYMS = {"TP", "FP", "FN", "PDF", "JSON", "HTTP", "UTC"}


def _strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_text(value: Any) -> str:
    """Return a comparison form stable across case, accents, and punctuation."""

    if value is None:
        return ""
    text = _strip_accents(str(value)).lower().replace("�", " ")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _parse_json_source(value: Any) -> Any:
    """Decode a serialized structured payload without changing plain text."""

    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped or stripped[0] not in "[{":
        return value
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return value


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n.;,:")


def _identifier(prefix: str, key: str) -> str:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _as_mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _polarity(value: Any, *, text: str = "") -> str:
    if isinstance(value, bool):
        return "NEGATED" if value else "AFFIRMED"
    normalized = normalize_text(value)
    if normalized in {"negated", "negative", "false", "否", "no", "not"}:
        return "NEGATED"
    if normalized in {"unknown", "uncertain", "not calculable"}:
        return "UNKNOWN"
    return "NEGATED" if _NEGATION_RE.search(text) else "AFFIRMED"


def _infer_triplet(text: str) -> tuple[str, str, str]:
    """Infer a lightweight subject/predicate/object triple for matching.

    This is not a legal parser.  It only provides a stable key for structured
    and text claims that use the same proposition; the claim text remains the
    auditable evidence shown to the caller.
    """

    value = _clean_text(text)
    match = _VERB_RE.search(value)
    if not match:
        return "", "", normalize_text(value)
    subject = normalize_text(_NEGATION_RE.sub(" ", value[: match.start()]))
    predicate = normalize_text(match.group(1))
    object_value = normalize_text(value[match.end() :])
    return subject, predicate, object_value


def _claim_from_item(item: Any, *, prefix: str = "claim") -> dict[str, Any] | None:
    if isinstance(item, str):
        text = _clean_text(item)
        if not text:
            return None
        subject, predicate, object_value = _infer_triplet(text)
        polarity = _polarity(None, text=text)
        key = _claim_key(subject, predicate, object_value, polarity, text)
        return {
            "id": _identifier(prefix, key),
            "text": text,
            "normalized": normalize_text(text),
            "subject": subject or None,
            "predicate": predicate or None,
            "object": object_value or None,
            "polarity": polarity,
            "key": key,
        }
    mapping = _as_mapping(item)
    if mapping is None:
        return None
    text_value = _first(mapping, "text", "claim", "content", "statement", "value")
    text = _clean_text(text_value) if text_value is not None else ""
    subject = _clean_text(_first(mapping, "subject", "actor", "source"))
    predicate = _clean_text(_first(mapping, "predicate", "relation", "action"))
    object_value = _clean_text(_first(mapping, "object", "target", "outcome"))
    if not text and not (subject or predicate or object_value):
        return None
    if not text:
        text = " ".join(part for part in (subject, predicate, object_value) if part)
    inferred_subject, inferred_predicate, inferred_object = _infer_triplet(text)
    subject = normalize_text(subject) or inferred_subject
    predicate = normalize_text(predicate) or inferred_predicate
    object_value = normalize_text(object_value) or inferred_object
    polarity = _polarity(
        _first(mapping, "polarity", "negated", "is_negated"), text=text
    )
    key = _claim_key(subject, predicate, object_value, polarity, text)
    explicit_id = _first(mapping, "id", "claim_id", "fact_id")
    return {
        "id": str(explicit_id) if explicit_id is not None else _identifier(prefix, key),
        "text": text,
        "normalized": normalize_text(text),
        "subject": subject or None,
        "predicate": predicate or None,
        "object": object_value or None,
        "polarity": polarity,
        "key": key,
    }


def _claim_key(
    subject: str, predicate: str, object_value: str, polarity: str, text: str
) -> str:
    if subject or predicate or object_value:
        return f"{subject}|{predicate}|{object_value}|{polarity}"
    return f"text|{normalize_text(text)}|{polarity}"


def _source_dimension(source: Any, dimension: str) -> tuple[Any, bool]:
    """Return a dimension value and whether the dimension was explicitly given."""

    source = _parse_json_source(source)
    if isinstance(source, Mapping):
        for key in _DIMENSION_KEYS[dimension]:
            if key in source:
                return source[key], True
        for wrapper in _WRAPPER_KEYS:
            if wrapper in source:
                value, present = _source_dimension(source[wrapper], dimension)
                if present:
                    return value, True
        if "gold" in source and isinstance(source["gold"], Mapping):
            return _source_dimension(source["gold"], dimension)
    return source, isinstance(source, (list, tuple))


def _text_from_source(source: Any) -> str:
    source = _parse_json_source(source)
    if isinstance(source, str):
        return source
    if isinstance(source, Mapping):
        direct = _first(source, "text", "answer", "content", "body", "draft")
        if isinstance(direct, str):
            return direct
        for wrapper in _WRAPPER_KEYS:
            if wrapper in source:
                text = _text_from_source(source[wrapper])
                if text:
                    return text
        values: list[str] = []
        ignored = {
            "gold",
            "reference",
            "source",
            "citations",
            "citation_ids",
            "warnings",
            "metadata",
            "status",
        }
        for key, value in source.items():
            if key in ignored or key in _DIMENSION_KEYS["claims"]:
                continue
            if isinstance(value, str):
                values.append(value)
        return " ".join(values)
    if isinstance(source, Sequence) and not isinstance(source, (bytes, bytearray)):
        return " ".join(_text_from_source(value) for value in source)
    return ""


def _structured_items(source: Any, dimension: str) -> tuple[list[Any], bool, str | None]:
    value, present = _source_dimension(source, dimension)
    if not present:
        return [], False, None
    if value is None:
        return [], True, "gold_dimension_is_null"
    if isinstance(value, Mapping):
        return [value], True, None
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value), True, None
    return [], True, "gold_dimension_must_be_a_list_or_object"


def _deduplicate(items: Iterable[dict[str, Any]], key_fn: Callable[[dict[str, Any]], str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        key = key_fn(item)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _claim_match_key(item: Mapping[str, Any]) -> str:
    key = str(item.get("key") or "")
    if key:
        return key
    return normalize_text(item.get("text"))


def extract_atomic_claims(source: Any) -> list[dict[str, Any]]:
    """Extract atomic claims from text or normalize a structured claim list.

    Structured input takes precedence when ``claims``/``atomic_claims`` is
    present.  Text is split at sentence, line, and selected coordinating-clause
    boundaries.  Every returned claim has a deterministic id and key.
    """

    items, present, _ = _structured_items(source, "claims")
    if present:
        normalized = (_claim_from_item(item) for item in items)
        return _deduplicate((item for item in normalized if item), _claim_match_key)
    text = _text_from_source(source)
    claims: list[dict[str, Any]] = []
    for sentence in _SENTENCE_RE.split(text):
        for clause in _CLAUSE_RE.split(sentence):
            cleaned = _clean_text(clause)
            if not cleaned:
                continue
            item = _claim_from_item(cleaned)
            if item is not None:
                claims.append(item)
    return _deduplicate(claims, _claim_match_key)


extract_claims = extract_atomic_claims


def _entity_type(value: Any) -> str:
    normalized = normalize_text(value)
    aliases = {
        "org": "ORGANIZATION",
        "organization": "ORGANIZATION",
        "organizacion": "ORGANIZATION",
        "legal entity": "ORGANIZATION",
        "entidad juridica": "ORGANIZATION",
        "person": "PERSON",
        "persona": "PERSON",
        "court": "COURT",
        "tribunal": "COURT",
        "legal instrument": "LEGAL_INSTRUMENT",
        "instrumento juridico": "LEGAL_INSTRUMENT",
        "law": "LEGAL_INSTRUMENT",
        "norma": "LEGAL_INSTRUMENT",
        "case": "CASE",
        "expediente": "CASE",
    }
    return aliases.get(normalized, str(value).upper().strip() if value else "ENTITY")


def _entity_from_item(item: Any) -> dict[str, Any] | None:
    if isinstance(item, str):
        text = _clean_text(item)
        if not text:
            return None
        kind = "ENTITY"
    else:
        mapping = _as_mapping(item)
        if mapping is None:
            return None
        raw = _first(
            mapping,
            "text",
            "name",
            "canonical_name",
            "value",
            "entity",
            "mention",
        )
        text = _clean_text(raw)
        if not text:
            return None
        kind = _entity_type(_first(mapping, "type", "entity_type", "category"))
    normalized = normalize_text(text)
    key = f"{kind}|{normalized}"
    explicit_id = (
        _first(item, "id", "entity_id") if isinstance(item, Mapping) else None
    )
    return {
        "id": str(explicit_id) if explicit_id is not None else _identifier("entity", key),
        "text": text,
        "normalized": normalized,
        "type": kind,
        "key": key,
    }


def _add_entity(result: list[dict[str, Any]], text: str, kind: str) -> None:
    item = _entity_from_item({"text": text, "type": kind})
    if item is not None:
        result.append(item)


def extract_legal_entities(source: Any) -> list[dict[str, Any]]:
    """Extract named legal entities and instruments from text or gold-like data."""

    items, present, _ = _structured_items(source, "entities")
    if present:
        normalized = (_entity_from_item(item) for item in items)
        return _deduplicate((item for item in normalized if item), lambda i: str(i["key"]))
    text = _text_from_source(source)
    entities: list[dict[str, Any]] = []
    for match in _LEGAL_INSTRUMENT_RE.finditer(text):
        _add_entity(entities, match.group(0), "LEGAL_INSTRUMENT")
    for match in _CASE_RE.finditer(text):
        _add_entity(entities, match.group(0), "CASE")
    for match in _COURT_RE.finditer(text):
        _add_entity(entities, _clean_text(match.group(0)), "COURT")
    for match in _ORG_RE.finditer(text):
        _add_entity(entities, _clean_text(match.group(0)), "ORGANIZATION")
    for match in _PERSON_RE.finditer(text):
        _add_entity(entities, _clean_text(match.group(1)), "PERSON")
    for match in _ACRONYM_RE.finditer(text):
        if match.group(0) not in _NOISE_ACRONYMS:
            _add_entity(entities, match.group(0), "ORGANIZATION")
    return _deduplicate(entities, lambda i: str(i["key"]))


extract_entities = extract_legal_entities


def _contradiction_from_item(item: Any) -> dict[str, Any] | None:
    mapping = _as_mapping(item)
    if mapping is None:
        if isinstance(item, str) and _clean_text(item):
            text = _clean_text(item)
            key = f"text|{normalize_text(text)}"
            return {
                "id": _identifier("contradiction", key),
                "text": text,
                "claim_a": None,
                "claim_b": None,
                "reason": None,
                "normalized": normalize_text(text),
                "key": key,
            }
        return None
    left = _first(mapping, "claim_a", "left", "left_claim", "first", "claim1")
    right = _first(mapping, "claim_b", "right", "right_claim", "second", "claim2")
    if left is None and right is None:
        text = _clean_text(_first(mapping, "text", "reason", "description"))
        if not text:
            return None
        key = f"text|{normalize_text(text)}"
    else:
        left_claim = _claim_from_item(left, prefix="claim")
        right_claim = _claim_from_item(right, prefix="claim")
        left_key = _claim_match_key(left_claim) if left_claim else normalize_text(left)
        right_key = _claim_match_key(right_claim) if right_claim else normalize_text(right)
        if not left_key or not right_key:
            return None
        key = "pair|" + "|".join(sorted((left_key, right_key)))
        text = _clean_text(_first(mapping, "text", "reason", "description"))
    explicit_id = _first(mapping, "id", "contradiction_id", "conflict_id")
    return {
        "id": str(explicit_id) if explicit_id is not None else _identifier("contradiction", key),
        "text": text,
        "claim_a": left,
        "claim_b": right,
        "reason": _clean_text(_first(mapping, "reason", "description")) or None,
        "normalized": normalize_text(text),
        "key": key,
    }


def _contradiction_match_key(item: Mapping[str, Any]) -> str:
    return str(item.get("key") or normalize_text(item.get("text")))


def _base_claim_key(claim: Mapping[str, Any]) -> str:
    subject = normalize_text(claim.get("subject"))
    predicate = normalize_text(claim.get("predicate"))
    if subject or predicate:
        return f"{subject}|{predicate}"
    text = normalize_text(claim.get("text"))
    text = _NEGATION_RE.sub(" ", text)
    return text


def extract_contradictions(source: Any) -> list[dict[str, Any]]:
    """Find explicit structured contradictions or conflicting claim pairs.

    A pair conflicts when it has the same inferred subject/predicate and a
    different object or polarity.  This conservative rule avoids treating
    unrelated legal propositions as contradictions.
    """

    items, present, _ = _structured_items(source, "contradictions")
    if present:
        normalized = (_contradiction_from_item(item) for item in items)
        return _deduplicate((item for item in normalized if item), _contradiction_match_key)
    claims = extract_atomic_claims(source)
    contradictions: list[dict[str, Any]] = []
    for index, left in enumerate(claims):
        for right in claims[index + 1 :]:
            if _base_claim_key(left) != _base_claim_key(right):
                continue
            object_differs = normalize_text(left.get("object")) != normalize_text(
                right.get("object")
            )
            polarity_differs = left.get("polarity") != right.get("polarity")
            if not (object_differs or polarity_differs):
                continue
            key = "pair|" + "|".join(sorted((_claim_match_key(left), _claim_match_key(right))))
            contradictions.append(
                {
                    "id": _identifier("contradiction", key),
                    "text": f"{left['text']} / {right['text']}",
                    "claim_a": left["id"],
                    "claim_b": right["id"],
                    "reason": "same subject/predicate with different object or polarity",
                    "normalized": normalize_text(f"{left['text']} {right['text']}"),
                    "key": key,
                }
            )
    return _deduplicate(contradictions, _contradiction_match_key)


def _gold_items(gold: Any, dimension: str) -> tuple[list[dict[str, Any]], str | None]:
    items, present, reason = _structured_items(gold, dimension)
    if not present:
        return [], "missing_gold_dimension"
    if reason is not None:
        return [], reason
    converted: list[dict[str, Any]] = []
    converter: Callable[[Any], dict[str, Any] | None]
    if dimension == "claims":
        converter = lambda item: _claim_from_item(item, prefix="gold-claim")
    elif dimension == "entities":
        converter = _entity_from_item
    else:
        converter = _contradiction_from_item
    for item in items:
        converted_item = converter(item)
        if converted_item is None:
            return [], "invalid_gold_item"
        converted.append(converted_item)
    return converted, None


def _entity_match_key(item: Mapping[str, Any]) -> str:
    normalized = normalize_text(item.get("normalized") or item.get("text"))
    kind = _entity_type(item.get("type"))
    return f"{kind}|{normalized}"


def _match_keys(item: Mapping[str, Any], dimension: str) -> set[str]:
    if dimension == "claims":
        keys = {_claim_match_key(item)}
        text_key = normalize_text(item.get("text"))
        if text_key:
            keys.add(f"text|{text_key}|{item.get('polarity', 'AFFIRMED')}")
        return {key for key in keys if key}
    if dimension == "entities":
        normalized = normalize_text(item.get("normalized") or item.get("text"))
        kind = _entity_type(item.get("type"))
        return {f"{kind}|{normalized}", normalized} if normalized else set()
    return {_contradiction_match_key(item)} if _contradiction_match_key(item) else set()


def _score_items(
    predictions: list[dict[str, Any]], gold: list[dict[str, Any]], dimension: str
) -> dict[str, Any]:
    unmatched_predictions = set(range(len(predictions)))
    unmatched_gold = set(range(len(gold)))
    matches: list[tuple[int, int]] = []
    for gold_index, gold_item in enumerate(gold):
        gold_keys = _match_keys(gold_item, dimension)
        for prediction_index in sorted(unmatched_predictions):
            if gold_keys.intersection(_match_keys(predictions[prediction_index], dimension)):
                matches.append((gold_index, prediction_index))
                unmatched_gold.discard(gold_index)
                unmatched_predictions.discard(prediction_index)
                break
    verdicts: list[dict[str, Any]] = []
    for gold_index, prediction_index in matches:
        verdicts.append(
            {
                "status": TP,
                "gold_id": gold[gold_index]["id"],
                "prediction_id": predictions[prediction_index]["id"],
            }
        )
    for prediction_index in sorted(unmatched_predictions):
        verdicts.append({"status": FP, "prediction_id": predictions[prediction_index]["id"]})
    for gold_index in sorted(unmatched_gold):
        verdicts.append({"status": FN, "gold_id": gold[gold_index]["id"]})
    tp = len(matches)
    fp = len(unmatched_predictions)
    fn = len(unmatched_gold)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    counts = {TP: tp, FP: fp, FN: fn, NOT_CALCULABLE: 0}
    return {
        "dimension": dimension,
        "status": "CALCULATED",
        "verdicts": verdicts,
        "items": verdicts,
        "counts": counts,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "not_calculable": 0,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "gold_count": len(gold),
        "prediction_count": len(predictions),
    }


def score_dimension(prediction: Any, gold: Any, dimension: str) -> dict[str, Any]:
    """Score one dimension using explicit structured gold.

    ``dimension`` is one of ``claims``, ``entities``, or ``contradictions``.
    ``gold`` may be a list for that dimension or an envelope containing the
    corresponding key.  Gold absence, null, or malformed items is
    ``NOT_CALCULABLE``.  An explicit empty gold list is valid and calculable.
    """

    if dimension not in DIMENSIONS:
        raise ValueError(f"unknown claims dimension: {dimension!r}")
    gold_items, reason = _gold_items(gold, dimension)
    if reason is not None:
        counts = {TP: 0, FP: 0, FN: 0, NOT_CALCULABLE: 1}
        return {
            "dimension": dimension,
            "status": NOT_CALCULABLE,
            "reason": reason,
            "verdicts": [],
            "items": [],
            "counts": counts,
            "tp": None,
            "fp": None,
            "fn": None,
            "not_calculable": 1,
            "precision": None,
            "recall": None,
            "f1": None,
            "gold_count": None,
            "prediction_count": len(_prediction_items(prediction, dimension)),
        }
    predictions = _prediction_items(prediction, dimension)
    return _score_items(predictions, gold_items, dimension)


def _prediction_items(prediction: Any, dimension: str) -> list[dict[str, Any]]:
    if dimension == "claims":
        return extract_atomic_claims(prediction)
    if dimension == "entities":
        return extract_legal_entities(prediction)
    return extract_contradictions(prediction)


def score_claims(prediction: Any, gold: Any) -> dict[str, Any]:
    """Score atomic claims against explicit gold claims."""

    return score_dimension(prediction, gold, "claims")


def score_entities(prediction: Any, gold: Any) -> dict[str, Any]:
    """Score legal entities against explicit gold entities."""

    return score_dimension(prediction, gold, "entities")


def score_contradictions(prediction: Any, gold: Any) -> dict[str, Any]:
    """Score contradictions against explicit gold contradictions."""

    return score_dimension(prediction, gold, "contradictions")


def evaluate(prediction: Any, gold: Any) -> dict[str, Any]:
    """Evaluate all dimensions without ever deriving truth from prediction."""

    dimensions = {
        "claims": score_claims(prediction, gold),
        "entities": score_entities(prediction, gold),
        "contradictions": score_contradictions(prediction, gold),
    }
    calculable = [value for value in dimensions.values() if value["status"] == "CALCULATED"]
    if not calculable:
        status = NOT_CALCULABLE
    elif len(calculable) == len(DIMENSIONS):
        status = "CALCULATED"
    else:
        status = "PARTIAL"
    summary = {
        "status": status,
        "tp": sum(int(value["tp"] or 0) for value in calculable),
        "fp": sum(int(value["fp"] or 0) for value in calculable),
        "fn": sum(int(value["fn"] or 0) for value in calculable),
        "not_calculable": sum(value["status"] == NOT_CALCULABLE for value in dimensions.values()),
    }
    return {
        "schema_version": "benchmark-v2.claims.v1",
        "status": status,
        "dimensions": dimensions,
        "claims": dimensions["claims"],
        "entities": dimensions["entities"],
        "contradictions": dimensions["contradictions"],
        "summary": summary,
    }


evaluate_claims = evaluate


__all__ = [
    "DIMENSIONS",
    "FN",
    "FP",
    "NOT_CALCULABLE",
    "TP",
    "evaluate",
    "evaluate_claims",
    "extract_atomic_claims",
    "extract_claims",
    "extract_contradictions",
    "extract_entities",
    "extract_legal_entities",
    "normalize_text",
    "score_claims",
    "score_contradictions",
    "score_dimension",
    "score_entities",
]
