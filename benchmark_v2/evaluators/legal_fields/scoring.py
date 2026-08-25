"""Deterministic scoring for mandatory legal fields.

The public entry point is :func:`score_legal_fields`.  It evaluates the five
fields that are common to the legal benchmark (``norma``, ``fecha``,
``plazo``, ``expediente`` and ``referencias``), plus any fields supplied by a
caller.  Input can be a mapping containing those fields, a mapping under a
``fields``/``legal_fields`` wrapper, or a legal-text string.

There are two deliberately separate ways in which a metric can be absent:

* ``NOT_APPLICABLE`` means the case explicitly declares that a field does not
  apply (for example, no deadline exists).
* ``NOT_CALCULABLE`` means there is no usable gold value or the field cannot
  be interpreted.  It is excluded from coverage and accuracy denominators.

An absent prediction for an applicable gold field is ``MISSING`` and an
unusable prediction is ``INVALID``.  Neither is silently converted to
``NOT_APPLICABLE``.
"""

from __future__ import annotations

import datetime as _datetime
import math
import re
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .models import (
    CORRECT,
    INCORRECT,
    INVALID,
    MISSING,
    NOT_APPLICABLE,
    NOT_CALCULABLE,
    PARTIAL,
    FieldScore,
    FieldSpec,
)

DEFAULT_FIELDS = ("norma", "fecha", "plazo", "expediente", "referencias")
REQUIRED_FIELDS = DEFAULT_FIELDS

_ALIASES: dict[str, tuple[str, ...]] = {
    "norma": ("norma", "normas", "normas_citadas", "marco_normativo", "legal_basis"),
    "fecha": ("fecha", "date", "fecha_emision", "fecha_vigencia", "fecha_plazo_vigencia"),
    "plazo": ("plazo", "term", "duration", "deadline", "vigencia"),
    "expediente": ("expediente", "case_number", "numero_expediente", "case_id"),
    "referencias": (
        "referencias",
        "referencias_normativas",
        "references",
        "articulos",
        "articulos_resolutivos",
        "article_references",
    ),
}

_MARKERS = {
    "not_applicable": {
        NOT_APPLICABLE,
        "NA",
        "N/A",
        "NO_APLICA",
        "NO APLICA",
        "NO_CORRESPONDE",
        "NO CORRESPONDE",
        "NOT APPLICABLE",
        "NO_APPLICABLE",
    },
    "not_calculable": {
        NOT_CALCULABLE,
        "NOT CALCULABLE",
        "NO_CALCULABLE",
        "NO CALCULABLE",
        "UNAVAILABLE",
        "UNKNOWN",
    },
    "missing": {
        MISSING,
        "AUSENTE",
        "FALTANTE",
        "MISSING_VALUE",
        "DATO_PENDIENTE",
        "DATO PENDIENTE",
    },
}

_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}
_UNITS = {
    "dia": "day",
    "dias": "day",
    "día": "day",
    "días": "day",
    "day": "day",
    "days": "day",
    "semana": "week",
    "semanas": "week",
    "week": "week",
    "weeks": "week",
    "mes": "month",
    "meses": "month",
    "month": "month",
    "months": "month",
    "año": "year",
    "años": "year",
    "ano": "year",
    "anos": "year",
    "year": "year",
    "years": "year",
}
_NUMBER_WORDS = {
    "cero": 0,
    "uno": 1,
    "una": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
    "once": 11,
    "doce": 12,
    "trece": 13,
    "catorce": 14,
    "quince": 15,
    "dieciseis": 16,
    "dieciséis": 16,
    "diecisiete": 17,
    "dieciocho": 18,
    "diecinueve": 19,
    "veinte": 20,
    "treinta": 30,
    "cuarenta": 40,
    "cincuenta": 50,
    "sesenta": 60,
    "setenta": 70,
    "ochenta": 80,
    "noventa": 90,
    "cien": 100,
    "ciento": 100,
}

_NORM_RE = re.compile(
    r"\b(decreto(?:-ley)?|ley|resoluci[oó]n|decisi[oó]n\s+administrativa|ordenanza)\s*"
    r"(?:n(?:ro\.?|[°ºo])?\s*)?([0-9]{1,3}(?:\.[0-9]{3})*|[0-9]{1,7})(?:\s*/\s*([0-9]{2,4}))?",
    re.IGNORECASE,
)
_DATE_TEXT_RE = re.compile(
    r"\b([0-9]{1,2})\s+de\s+([a-záéíóú]+)\s+de\s+([0-9]{4})\b", re.IGNORECASE
)
_DATE_NUM_RE = re.compile(r"\b([0-9]{1,2})[/-]([0-9]{1,2})[/-]([0-9]{2,4})\b")
_DATE_ISO_RE = re.compile(r"\b([0-9]{4})-([0-9]{2})-([0-9]{2})\b")
_TERM_RE = re.compile(
    r"(?<![\w])(?:dentro\s+de\s+|en\s+un\s+plazo\s+de\s+|por\s+)?"
    r"(\d{1,7}|[a-záéíóú]+)\s*(?:\((\d{1,7})\))?\s*"
    r"(d[ií]as?|semanas?|mes(?:es)?|a[nñ]os?|days?|weeks?|months?|years?)\b",
    re.IGNORECASE,
)
_EXP_RE = re.compile(
    r"\bexpediente\s*(?:n(?:ro\.?|[°ºo])?\s*)?([a-z0-9][a-z0-9:/._-]{2,})",
    re.IGNORECASE,
)
_ARTICLE_RE = re.compile(
    r"\b(?:art[ií]culo|art\.?)\s*([0-9]{1,5})"
    r"(?:\s*[,;]?\s*(?:inciso|apartado)\s*([a-z0-9]{1,4}))?",
    re.IGNORECASE,
)


def normalize_text(value: Any) -> str:
    """Case/diacritic/spacing-insensitive text normalisation."""

    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.lower().replace("�", " ")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _marker(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    raw = value.strip().upper()
    compact = re.sub(r"\s+", " ", raw)
    for status, markers in _MARKERS.items():
        if raw in markers or compact in markers:
            return status
    return None


def _is_mapping(value: Any) -> bool:
    return isinstance(value, Mapping)


def _unwrap(value: Any, *, expected: bool) -> tuple[str | None, Any, bool]:
    """Return marker, payload, and whether a value key was explicitly given."""

    # ``None`` in a prediction is an explicit missing value.  A ``None`` gold
    # value is present but unusable, so it remains distinguishable and is
    # reported as NOT_CALCULABLE below.
    if value is None and not expected:
        return "missing", value, True
    marker = _marker(value)
    if marker is not None:
        return marker, value, True
    if not _is_mapping(value):
        return None, value, True
    mapping = dict(value)
    if "applicable" in mapping or "is_applicable" in mapping or "applies" in mapping:
        applies = mapping.get("applicable", mapping.get("is_applicable", mapping.get("applies")))
        if applies is False:
            return "not_applicable", value, True
        if applies is not True and applies is not None:
            return "not_calculable", value, True
    for key in ("value", "expected", "reference", "gold", "prediction", "predicted", "candidate", "answer"):
        if key in mapping:
            payload = mapping[key]
            marker = _marker(payload)
            return marker, payload, True
    # A mapping without a recognised wrapper can itself be a meaningful custom
    # value.  It is considered explicitly present and canonicalised as a map.
    return None, value, True


def _extract_mapping(value: Any, *, expected: bool) -> Mapping[str, Any] | None:
    if not _is_mapping(value):
        return None
    mapping = dict(value)
    for wrapper in ("legal_fields", "fields", "field_values", "expected", "reference", "prediction", "output"):
        nested = mapping.get(wrapper)
        if _is_mapping(nested):
            # A direct field wins only when no nested field is available.  This
            # permits records to carry metadata alongside their legal fields.
            if any(key in mapping for key in DEFAULT_FIELDS):
                return mapping
            return nested
    return mapping


def _get_field(mapping: Mapping[str, Any] | None, name: str, spec: FieldSpec) -> tuple[bool, Any]:
    if mapping is None:
        return False, None
    for key in (name, *spec.aliases, *_ALIASES.get(name, ())):
        if key in mapping:
            return True, mapping[key]
    return False, None


def _as_number_word(value: str) -> int | None:
    text = normalize_text(value)
    if text in _NUMBER_WORDS:
        return _NUMBER_WORDS[text]
    return None


def _canonical_norma(value: Any) -> Any:
    if isinstance(value, Mapping):
        kind = value.get("type", value.get("kind", ""))
        number = value.get("number", value.get("numero"))
        year = value.get("year", value.get("ano", value.get("año")))
        if number is not None:
            return f"{normalize_text(kind)}:{int(str(number).replace('.', ''))}:{year or '-'}"
    values = _iter_values(value)
    claims: list[str] = []
    for raw in values:
        text = str(raw)
        matches = list(_NORM_RE.finditer(text))
        if matches:
            claims.extend(
                f"{normalize_text(match.group(1)).replace(' ', '_')}:{int(match.group(2).replace('.', ''))}:{match.group(3) or '-'}"
                for match in matches
            )
        else:
            canonical = normalize_text(text)
            if canonical:
                claims.append(canonical)
    return tuple(sorted(claims)) if _is_collection(value) or len(claims) != 1 else claims[0]


def _parse_date(value: Any) -> str | None:
    if isinstance(value, _datetime.datetime):
        return value.date().isoformat()
    if isinstance(value, _datetime.date):
        return value.isoformat()
    if not isinstance(value, str):
        return None
    text = unicodedata.normalize("NFKC", value).strip()
    match = _DATE_ISO_RE.search(text)
    if match:
        try:
            return _datetime.date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
        except ValueError:
            return None
    match = _DATE_NUM_RE.search(text)
    if match:
        year = int(match.group(3))
        year += 2000 if year < 100 else 0
        try:
            return _datetime.date(year, int(match.group(2)), int(match.group(1))).isoformat()
        except ValueError:
            return None
    match = _DATE_TEXT_RE.search(text)
    if match:
        month = _MONTHS.get(normalize_text(match.group(2)))
        if month is None:
            return None
        try:
            return _datetime.date(int(match.group(3)), month, int(match.group(1))).isoformat()
        except ValueError:
            return None
    return None


def _canonical_fecha(value: Any) -> Any:
    values = _iter_values(value)
    parsed = [_parse_date(item) for item in values]
    if any(item is None for item in parsed):
        raise ValueError("fecha must contain a valid date")
    result = tuple(sorted(parsed)) if _is_collection(value) else parsed[0] if parsed else None
    return result


def _canonical_plazo_one(value: Any) -> str | None:
    if isinstance(value, Mapping):
        amount = value.get("amount", value.get("value", value.get("cantidad")))
        unit = value.get("unit", value.get("unidad"))
        if amount is None or unit is None:
            return None
        word_amount = _as_number_word(str(amount)) if isinstance(amount, str) else None
        try:
            amount_value = int(word_amount if word_amount is not None else amount)
        except (TypeError, ValueError):
            return None
        unit_value = _UNITS.get(str(unit).lower(), _UNITS.get(normalize_text(unit)))
        return f"{amount_value}:{unit_value}" if unit_value else None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return None
    text = unicodedata.normalize("NFKC", str(value))
    match = _TERM_RE.search(text)
    if not match:
        return None
    amount = match.group(2) or match.group(1)
    amount_value = _as_number_word(amount)
    if amount_value is None:
        try:
            amount_value = int(amount)
        except ValueError:
            return None
    unit = _UNITS.get(match.group(3).lower(), _UNITS.get(normalize_text(match.group(3))))
    return f"{amount_value}:{unit}" if unit else None


def _canonical_plazo(value: Any) -> Any:
    values = _iter_values(value)
    parsed = [_canonical_plazo_one(item) for item in values]
    if any(item is None for item in parsed):
        raise ValueError("plazo must contain an amount and unit")
    return tuple(sorted(parsed)) if _is_collection(value) else parsed[0] if parsed else None


def _canonical_expediente_one(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = _EXP_RE.search(value)
    if match:
        value = match.group(1)
    canonical = re.sub(r"[^A-Za-z0-9]", "", value).upper()
    return canonical if len(canonical) >= 3 else None


def _canonical_expediente(value: Any) -> Any:
    values = _iter_values(value)
    parsed = [_canonical_expediente_one(item) for item in values]
    if any(item is None for item in parsed):
        raise ValueError("expediente must contain a non-empty identifier")
    return tuple(sorted(parsed)) if _is_collection(value) else parsed[0] if parsed else None


def _canonical_referencia_one(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    matches = list(_ARTICLE_RE.finditer(value))
    if matches:
        return "|".join(
            f"article:{int(match.group(1))}:{normalize_text(match.group(2)) or '-'}"
            for match in matches
        )
    canonical = normalize_text(value)
    return canonical or None


def _canonical_referencias(value: Any) -> Any:
    values = _iter_values(value)
    parsed = [_canonical_referencia_one(item) for item in values]
    if any(item is None for item in parsed):
        raise ValueError("referencias must contain non-empty values")
    return tuple(sorted(parsed)) if _is_collection(value) else parsed[0] if parsed else None


def _canonical_generic(value: Any) -> Any:
    if isinstance(value, Mapping):
        return tuple(sorted((str(key), _canonical_generic(item)) for key, item in value.items()))
    if _is_collection(value):
        return tuple(sorted((_canonical_generic(item) for item in value), key=repr))
    if isinstance(value, str):
        result = normalize_text(value)
        if not result:
            raise ValueError("value must not be blank")
        return result
    if value is None or isinstance(value, bool):
        raise ValueError("value must not be null or boolean")
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("value must be finite")
        return value
    raise ValueError("unsupported value")


def _iter_values(value: Any) -> list[Any]:
    if _is_collection(value):
        return list(value)
    return [value]


def _is_collection(value: Any) -> bool:
    return isinstance(value, (list, tuple, set, frozenset))


def _default_spec(name: str) -> FieldSpec:
    kind = name.lower()
    if kind == "norma":
        return FieldSpec(name, normalizer=_canonical_norma, kind=kind, aliases=_ALIASES[kind])
    if kind == "fecha":
        return FieldSpec(name, normalizer=_canonical_fecha, kind=kind, aliases=_ALIASES[kind])
    if kind == "plazo":
        return FieldSpec(name, normalizer=_canonical_plazo, kind=kind, aliases=_ALIASES[kind])
    if kind == "expediente":
        return FieldSpec(name, normalizer=_canonical_expediente, kind=kind, aliases=_ALIASES[kind])
    if kind == "referencias":
        return FieldSpec(name, normalizer=_canonical_referencias, kind=kind, aliases=_ALIASES[kind])
    return FieldSpec(name, normalizer=_canonical_generic, kind=kind)


def _coerce_spec(name: str, value: Any = None) -> FieldSpec:
    if isinstance(value, FieldSpec):
        return value if value.name == name else FieldSpec(name, **{**value.__dict__, "name": name})
    base = _default_spec(name)
    if value is None:
        return base
    if callable(value):
        return FieldSpec(name, normalizer=base.normalizer, validator=value, kind=base.kind, aliases=base.aliases)
    if not _is_mapping(value):
        return base
    config = dict(value)
    kind = str(config.get("kind", config.get("type", base.kind or name)))
    kind_base = _default_spec(kind) if kind in DEFAULT_FIELDS else base
    normalizer = config.get("normalizer", config.get("normalize", kind_base.normalizer))
    validator = config.get("validator", config.get("validate"))
    comparator = config.get("comparator", config.get("compare"))
    aliases = tuple(config.get("aliases", kind_base.aliases))
    metadata = {key: item for key, item in config.items() if key not in {
        "normalizer", "normalize", "validator", "validate", "comparator", "compare",
        "aliases", "applicable", "required", "kind", "type",
    }}
    return FieldSpec(
        name=name,
        normalizer=normalizer,
        validator=validator,
        comparator=comparator,
        aliases=aliases,
        applicable=config.get("applicable"),
        required=bool(config.get("required", True)),
        kind=kind,
        metadata=metadata,
    )


def _resolve_specs(
    fields: Sequence[str] | Mapping[str, Any] | Sequence[FieldSpec] | None,
    configurable_fields: Sequence[str] | Mapping[str, Any] | Sequence[FieldSpec] | None,
    field_config: Mapping[str, Any] | None,
) -> list[FieldSpec]:
    selected: list[tuple[str, Any]] = []
    if fields is None:
        selected.extend((name, None) for name in DEFAULT_FIELDS)
    elif _is_mapping(fields):
        selected.extend((str(name), config) for name, config in dict(fields).items())
    else:
        for item in fields:
            if isinstance(item, FieldSpec):
                selected.append((item.name, item))
            else:
                selected.append((str(item), None))
    if configurable_fields is not None:
        if _is_mapping(configurable_fields):
            selected.extend((str(name), config) for name, config in dict(configurable_fields).items())
        else:
            selected.extend((item.name, item) if isinstance(item, FieldSpec) else (str(item), None) for item in configurable_fields)
    configs = dict(field_config or {})
    seen: set[str] = set()
    result: list[FieldSpec] = []
    for name, config in selected:
        if name in seen:
            continue
        seen.add(name)
        result.append(_coerce_spec(name, configs.get(name, config)))
    return result


def _extract_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if not _is_mapping(value):
        return None
    for key in ("text", "content", "output", "answer", "draft"):
        if isinstance(value.get(key), str):
            return value[key]
    return None


def extract_legal_fields(text: str) -> dict[str, list[str]]:
    """Extract typed benchmark fields from a legal text output.

    Extraction is intentionally conservative: no key is emitted when the
    corresponding pattern is absent, allowing the scorer to report MISSING.
    """

    source = unicodedata.normalize("NFKC", text or "")
    result: dict[str, list[str]] = {}
    norms = [match.group(0) for match in _NORM_RE.finditer(source)]
    dates = [match.group(0) for match in (*_DATE_ISO_RE.finditer(source), *_DATE_NUM_RE.finditer(source), *_DATE_TEXT_RE.finditer(source))]
    terms = [match.group(0) for match in _TERM_RE.finditer(source)]
    expedientes = [match.group(0) for match in _EXP_RE.finditer(source)]
    references = [match.group(0) for match in _ARTICLE_RE.finditer(source)]
    if norms:
        result["norma"] = list(dict.fromkeys(norms))
    if dates:
        result["fecha"] = list(dict.fromkeys(dates))
    if terms:
        result["plazo"] = list(dict.fromkeys(terms))
    if expedientes:
        result["expediente"] = list(dict.fromkeys(expedientes))
    if references:
        result["referencias"] = list(dict.fromkeys(references))
    return result


def _prepare_candidate(candidate: Any, specs: Sequence[FieldSpec]) -> Mapping[str, Any] | None:
    mapping = _extract_mapping(candidate, expected=False)
    if mapping is not None:
        # A generic output/text wrapper should be parsed only if no recognised
        # field key exists; direct field values always take precedence.
        known = any(_get_field(mapping, spec.name, spec)[0] for spec in specs)
        if known:
            return mapping
    text = _extract_text(candidate)
    if text is not None:
        return extract_legal_fields(text)
    if isinstance(candidate, str):
        return extract_legal_fields(candidate)
    return mapping


def _validate_and_normalize(value: Any, spec: FieldSpec) -> tuple[bool, Any, str | None]:
    if value is None:
        return False, None, "null_value"
    try:
        if spec.validator is not None:
            checked = spec.validator(value)
            if checked is False or checked is None:
                return False, None, "validator_rejected"
            # Validators commonly return a cleaned replacement, while a
            # boolean True means retain the original payload.
            if checked is not True:
                value = checked
        if spec.normalizer is not None:
            value = spec.normalizer(value)
        if value is None:
            return False, None, "normalizer_rejected"
        return True, value, None
    except (TypeError, ValueError, KeyError, AttributeError, OverflowError) as exc:
        return False, None, str(exc) or "invalid_value"


def _match_values(expected: Any, predicted: Any, comparator: Callable[[Any, Any], bool | float] | None) -> dict[str, Any]:
    expected_values = list(expected) if _is_collection(expected) else [expected]
    predicted_values = list(predicted) if _is_collection(predicted) else [predicted]
    if comparator is None:
        def comparator(left: Any, right: Any) -> bool | float:  # type: ignore[no-redef]
            return left == right
    remaining = list(predicted_values)
    tp = 0
    weighted_tp = 0.0
    for gold in expected_values:
        best_index = None
        best_score = 0.0
        for index, guess in enumerate(remaining):
            result = comparator(gold, guess)
            score = float(result) if isinstance(result, (int, float)) and not isinstance(result, bool) else 1.0 if result else 0.0
            if score > best_score:
                best_index, best_score = index, score
        if best_index is not None and best_score > 0:
            tp += 1
            weighted_tp += best_score
            remaining.pop(best_index)
    fp = len(predicted_values) - tp
    fn = len(expected_values) - tp
    precision = weighted_tp / len(predicted_values) if predicted_values else None
    recall = weighted_tp / len(expected_values) if expected_values else None
    f1 = 2 * precision * recall / (precision + recall) if precision is not None and recall is not None and precision + recall else None
    exact = tp == len(expected_values) == len(predicted_values) and all(
        comparator(gold, guess) is True or comparator(gold, guess) == 1 for gold, guess in zip(expected_values, predicted_values)
    ) if len(expected_values) == len(predicted_values) else False
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1, "exact": exact}


def score_field(
    field: str,
    expected: Any,
    predicted: Any,
    *,
    spec: FieldSpec | Mapping[str, Any] | Callable[[Any], bool] | None = None,
) -> dict[str, Any]:
    """Score one field and return its dictionary representation."""

    field_spec = _coerce_spec(field, spec)
    expected_marker, expected_payload, expected_given = _unwrap(expected, expected=True)
    predicted_marker, predicted_payload, predicted_given = _unwrap(predicted, expected=False)
    if expected_marker == "not_applicable":
        return FieldScore(field, NOT_APPLICABLE, None, None, None, False, expected_given, predicted_given, not_applicable=True, expected=expected_payload, predicted=predicted_payload, reason="explicitly_not_applicable").to_dict()
    if expected_marker in {"not_calculable", "missing"} or not expected_given:
        return FieldScore(field, NOT_CALCULABLE, None, None, None, False, False, predicted_given, not_calculable=True, expected=expected_payload, predicted=predicted_payload, reason="gold_value_unavailable").to_dict()
    if _is_collection(expected_payload) and len(expected_payload) == 0:
        return FieldScore(field, NOT_APPLICABLE, None, None, None, False, True, predicted_given, not_applicable=True, expected=expected_payload, predicted=predicted_payload, reason="empty_gold_set_is_not_applicable").to_dict()
    expected_ok, expected_value, expected_reason = _validate_and_normalize(expected_payload, field_spec)
    if not expected_ok:
        return FieldScore(field, NOT_CALCULABLE, None, None, None, False, True, predicted_given, not_calculable=True, expected=expected_payload, predicted=predicted_payload, reason=expected_reason or "invalid_gold_value").to_dict()
    if predicted_marker == "not_applicable":
        return FieldScore(field, INVALID, 0.0, 0.0, 0.0, True, True, predicted_given, invalid=True, expected=expected_payload, predicted=predicted_payload, reason="prediction_declared_not_applicable").to_dict()
    if predicted_marker == "not_calculable":
        return FieldScore(field, NOT_CALCULABLE, None, None, None, True, True, False, not_calculable=True, expected=expected_payload, predicted=predicted_payload, reason="prediction_not_calculable").to_dict()
    if predicted_marker == "missing" or not predicted_given or predicted_payload is None:
        return FieldScore(field, MISSING, 0.0, 0.0, 0.0, True, True, False, missing=True, expected=expected_payload, predicted=predicted_payload, reason="prediction_missing").to_dict()
    if _is_collection(predicted_payload) and len(predicted_payload) == 0:
        return FieldScore(field, MISSING, 0.0, 0.0, 0.0, True, True, False, missing=True, expected=expected_payload, predicted=predicted_payload, reason="empty_prediction").to_dict()
    predicted_ok, predicted_value, predicted_reason = _validate_and_normalize(predicted_payload, field_spec)
    if not predicted_ok:
        return FieldScore(field, INVALID, 0.0, 0.0, 0.0, True, True, True, invalid=True, expected=expected_payload, predicted=predicted_payload, reason=predicted_reason or "invalid_prediction").to_dict()
    metrics = _match_values(expected_value, predicted_value, field_spec.comparator)
    accuracy = metrics["f1"]
    status = CORRECT if metrics["exact"] else PARTIAL if accuracy and accuracy > 0 else INCORRECT
    return FieldScore(
        field, status, accuracy, accuracy, 1.0, True, True, True,
        exact=metrics["exact"], expected=expected_payload, predicted=predicted_payload,
        precision=metrics["precision"], recall=metrics["recall"], f1=metrics["f1"],
        tp=metrics["tp"], fp=metrics["fp"], fn=metrics["fn"],
    ).to_dict()


def score_legal_fields(
    expected: Any = None,
    predicted: Any = None,
    *,
    reference: Any = None,
    candidate: Any = None,
    output: Any = None,
    prediction: Any = None,
    fields: Sequence[str] | Mapping[str, Any] | Sequence[FieldSpec] | None = None,
    required_fields: Sequence[str] | None = None,
    configurable_fields: Sequence[str] | Mapping[str, Any] | Sequence[FieldSpec] | None = None,
    field_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Score all required and configured fields for one legal case.

    ``required_fields`` is an alias for an explicit ``fields`` sequence and is
    useful to callers that want to keep the word *required* in their schema.
    When neither is supplied, the five benchmark defaults are evaluated.
    """

    # Benchmark records use all of ``expected``/``reference`` and
    # ``predicted``/``candidate``/``output`` in practice; accept the aliases at
    # this boundary while keeping positional use concise.
    if expected is None and reference is not None:
        expected = reference
    if predicted is None:
        if candidate is not None:
            predicted = candidate
        elif output is not None:
            predicted = output
        elif prediction is not None:
            predicted = prediction
    selected = fields if fields is not None else required_fields
    specs = _resolve_specs(selected, configurable_fields, field_config)
    expected_mapping = _extract_mapping(expected, expected=True)
    predicted_mapping = _prepare_candidate(predicted, specs)
    scored: dict[str, dict[str, Any]] = {}
    for spec in specs:
        expected_given, expected_value = _get_field(expected_mapping, spec.name, spec)
        predicted_given, predicted_value = _get_field(predicted_mapping, spec.name, spec)
        # A globally configured non-applicable field remains explicitly N/A;
        # case-level declarations still override this only when applicable.
        if spec.applicable is False and not expected_given:
            expected_value, expected_given = NOT_APPLICABLE, True
        scored[spec.name] = score_field(
            spec.name,
            expected_value if expected_given else NOT_CALCULABLE,
            predicted_value if predicted_given else MISSING,
            spec=spec,
        )

    fields_list = list(scored.values())
    applicable = [item for item in fields_list if item["applicable"]]
    calculable = [item for item in applicable if not item["not_calculable"]]
    valid = [item for item in calculable if not item["missing"] and not item["invalid"]]
    observed = [item for item in calculable if item["predicted_present"]]
    coverage = len(valid) / len(calculable) if calculable else None
    presence_coverage = len(observed) / len(calculable) if calculable else None
    accuracy = sum(float(item["accuracy"] or 0.0) for item in calculable) / len(calculable) if calculable else None
    conditional_accuracy = sum(float(item["accuracy"] or 0.0) for item in valid) / len(valid) if valid else None
    missing_fields = [item["field"] for item in fields_list if item["missing"]]
    invalid_fields = [item["field"] for item in fields_list if item["invalid"]]
    not_applicable_fields = [item["field"] for item in fields_list if item["not_applicable"]]
    not_calculable_fields = [item["field"] for item in fields_list if item["not_calculable"]]
    if not applicable:
        status = NOT_APPLICABLE if not not_calculable_fields else NOT_CALCULABLE
    elif not calculable:
        status = NOT_CALCULABLE
    elif missing_fields or invalid_fields or any(item["status"] != CORRECT for item in calculable):
        status = PARTIAL
    else:
        status = CORRECT
    result = {
        "status": status,
        "coverage": coverage,
        "coverage_ratio": coverage,
        "presence_coverage": presence_coverage,
        "accuracy": accuracy,
        "exactness": accuracy,
        "conditional_accuracy": conditional_accuracy,
        "fields": scored,
        "per_field": scored,
        "field_scores": {name: item["accuracy"] for name, item in scored.items()},
        "accuracy_by_field": {name: item["accuracy"] for name, item in scored.items()},
        "field_count": len(fields_list),
        "applicable_fields": len(applicable),
        "calculable_fields": len(calculable),
        "valid_fields": len(valid),
        "observed_fields": len(observed),
        "missing": len(missing_fields),
        "missing_count": len(missing_fields),
        "missing_fields": missing_fields,
        "invalid": len(invalid_fields),
        "invalid_count": len(invalid_fields),
        "invalid_fields": invalid_fields,
        "not_applicable": len(not_applicable_fields),
        "not_applicable_count": len(not_applicable_fields),
        "not_applicable_fields": not_applicable_fields,
        "not_calculable": len(not_calculable_fields),
        "not_calculable_count": len(not_calculable_fields),
        "not_calculable_fields": not_calculable_fields,
    }
    return result


# Friendly aliases used by different benchmark runners.
evaluate_legal_fields = score_legal_fields
score_fields = score_legal_fields
evaluate_fields = score_legal_fields
evaluate_case = score_legal_fields
score = score_legal_fields
compute_legal_field_scores = score_legal_fields


__all__ = [
    "DEFAULT_FIELDS",
    "REQUIRED_FIELDS",
    "compute_legal_field_scores",
    "evaluate_case",
    "evaluate_fields",
    "evaluate_legal_fields",
    "extract_legal_fields",
    "normalize_text",
    "score",
    "score_field",
    "score_fields",
    "score_legal_fields",
]
