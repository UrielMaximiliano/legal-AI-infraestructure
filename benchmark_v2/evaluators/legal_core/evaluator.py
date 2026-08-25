"""Auditable legal-core metrics for the historical holdout outputs.

The evaluator is deliberately conservative and deterministic.  It joins a
candidate output to the PDF-derived gold record, applies the prompt as a
disclosure mask, and scores only disclosed claims.  Missing historical chunk
text does not erase the legal score: it only limits the source-faithfulness
dimension to citation traceability.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any

CALCULATED = "CALCULATED"
NOT_RECONSTRUCTABLE = "NOT_RECONSTRUCTABLE"

_STOPWORDS = {
    "a", "al", "con", "como", "de", "del", "desde", "el", "en", "entre",
    "es", "la", "las", "lo", "los", "para", "por", "que", "se", "su", "sus",
    "un", "una", "y", "o", "e", "u", "del", "d", "n", "º", "articulo",
}
_MONTHS = (
    "enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|"
    "noviembre|diciembre"
)
_NORM_RE = re.compile(
    r"\b(decreto|ley|resoluci[oó]n|disposici[oó]n|decisi[oó]n\s+administrativa)"
    r"\s*(?:n(?:ro\.?|[°ºo])?\s*)?(\d{1,6})\s*(?:/|de\s*)\s*(\d{2,4})\b",
    re.IGNORECASE,
)
_DATE_WORD_RE = re.compile(
    rf"\b(\d{{1,2}})\s+de\s+({_MONTHS})\s+de\s+(\d{{4}})\b", re.IGNORECASE
)
_DATE_NUM_RE = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b")
_DURATION_RE = re.compile(
    r"\b(\d{1,5}|ciento\s+ochenta|noventa|sesenta|treinta|quince|diez)"
    r"(?:\s*\(\s*(\d{1,5})\s*\))?\s+"
    r"(d[ií�]as?|mes(?:es)?|a[nñ�]os?)(?:\s+h[aá�]biles?)?\b",
    re.IGNORECASE,
)
_ARTICLE_RE = re.compile(r"\bart[ií]culo\s+(\d{1,4})\b|\b(?:art\.?|art[íi]culo)\s*(\d{1,4})", re.IGNORECASE)
_JURISDICTION_RE = re.compile(r"\bjurisdicci[oó]n\s+(\d{1,3})\b", re.IGNORECASE)
_EXPEDIENTE_RE = re.compile(
    r"\b(?:expediente|expte\.?)\s+(?:n(?:ro\.?|[°ºo])?\s*)?([A-Z0-9:/._-]{4,})",
    re.IGNORECASE,
)
_AMOUNT_RE = re.compile(r"(?:\b(?:monto|importe|suma)\s*(?:de\s*)?|\$\s*)(\d[\d.,]*)\b", re.IGNORECASE)
_DNI_RE = re.compile(r"\b(?:dni|d\.n\.i\.?|documento(?:\s+nacional\s+de\s+identidad)?)\s*(?:nro?\.?\s*)?(\d{6,9})\b", re.IGNORECASE)
_CITATION_RE = re.compile(r"\bSRC-\d{3}\b", re.IGNORECASE)
_FORBIDDEN_PATTERNS = (
    ("prohibited_signature_or_closing", re.compile(r"\b(?:firma|firmado|archivad[oa]|archivado digitalmente)\b", re.IGNORECASE)),
    ("prohibited_publication_formula", re.compile(r"\b(?:publ[ií]quese|comun[ií]quese|d[eé]se a la direcci[oó]n nacional del registro oficial)\b", re.IGNORECASE)),
    ("invented_authority_date", re.compile(r"\bdado en la casa de gobierno\b", re.IGNORECASE)),
)
_POLARITY_PAIRS = (
    (re.compile(r"\bautoriza(?:r|do|da)?\b", re.IGNORECASE), re.compile(r"\bproh[ií]be|prohibir|prohibido\b", re.IGNORECASE)),
    (re.compile(r"\bpermite|permitir\b", re.IGNORECASE), re.compile(r"\bproh[ií]be|prohibir|prohibido\b", re.IGNORECASE)),
    (re.compile(r"\bdeber[aá]|debe\b", re.IGNORECASE), re.compile(r"\bno deber[aá]|no debe\b", re.IGNORECASE)),
    (re.compile(r"\bpuede|podr[aá]\b", re.IGNORECASE), re.compile(r"\bno puede|no podr[aá]\b", re.IGNORECASE)),
)
_NOISE_DEPENDENCIES = {
    "considerando", "considerando:", "la presidenta", "de la nacion argentina",
    "apellido y nombre/s",
}


def _strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def normalize_text(value: Any) -> str:
    """Normalize text for deterministic comparison without semantic guessing."""

    text = _strip_accents(str(value or "")).lower().replace("�", " ")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _tokens(value: Any) -> set[str]:
    return {
        token
        for token in normalize_text(value).split()
        if token not in _STOPWORDS and (len(token) > 1 or token.isdigit())
    }


def token_recall(expected: Any, candidate: Any) -> float:
    expected_tokens = _tokens(expected)
    if not expected_tokens:
        return 1.0
    return len(expected_tokens & _tokens(candidate)) / len(expected_tokens)


def flatten_output(value: Any) -> str:
    """Flatten the structured draft while excluding retrieval metadata."""

    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return " ".join(
            flatten_output(item)
            for key, item in value.items()
            if key not in {"sources", "warnings", "citation_ids", "source_url", "citation_id"}
        )
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return " ".join(flatten_output(item) for item in value)
    return ""


def _number_word(value: str) -> str:
    normalized = normalize_text(value)
    return {
        "ciento ochenta": "180", "noventa": "90", "sesenta": "60",
        "treinta": "30", "quince": "15", "diez": "10",
    }.get(normalized, normalized)


def extract_typed_claims(text: Any) -> set[str]:
    """Extract protected legal values used for contradiction detection."""

    source = _strip_accents(str(text or ""))
    claims: set[str] = set()
    for kind, number, year in _NORM_RE.findall(source):
        claims.add(f"norma:{normalize_text(kind)}:{int(number)}/{year}")
    for day, month, year in _DATE_WORD_RE.findall(source):
        claims.add(f"fecha:{int(day)}:{normalize_text(month)}:{year}")
    for day, month, year in _DATE_NUM_RE.findall(source):
        claims.add(f"fecha:{int(day)}:{int(month)}:{year}")
    for word_or_number, parenthesized_number, unit in _DURATION_RE.findall(source):
        unit_value = normalize_text(unit)
        unit_value = "dias" if unit_value.startswith("dia") else unit_value
        claims.add(f"plazo:{parenthesized_number or _number_word(word_or_number)}:{unit_value}")
    for first, second in _ARTICLE_RE.findall(source):
        claims.add(f"articulo:{int(first or second)}")
    for number in _JURISDICTION_RE.findall(source):
        claims.add(f"jurisdiccion:{int(number)}")
    for identifier in _EXPEDIENTE_RE.findall(source):
        claims.add(f"expediente:{normalize_text(identifier).replace(' ', '')}")
    for amount in _AMOUNT_RE.findall(source):
        claims.add(f"monto:{re.sub(r'[^0-9]', '', amount)}")
    for dni in _DNI_RE.findall(source):
        claims.add(f"dni:{dni}")
    return claims


def _gold_typed_claims(gold: Mapping[str, Any]) -> set[str]:
    """Parse gold norm pairs that are stored as ``1106 10`` rather than ``1106/10``."""

    claims: set[str] = set()
    candidates = gold.get("field_candidates")
    if not isinstance(candidates, Mapping):
        return claims
    for value in _iter_values(candidates.get("normas_citadas")):
        for number, year in re.findall(r"\b(\d{1,6})\s+(\d{2,4})\b", value):
            claims.add(f"norma:decreto:{int(number)}/{year}")
    return claims


def _structured_article_claims(value: Any) -> set[str]:
    claims: set[str] = set()
    if isinstance(value, Mapping):
        number = value.get("number")
        if isinstance(number, int) and not isinstance(number, bool):
            claims.add(f"articulo:{number}")
        for item in value.values():
            claims.update(_structured_article_claims(item))
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        for item in value:
            claims.update(_structured_article_claims(item))
    return claims


def _iter_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, Mapping):
        return [str(item) for item in value.values() if isinstance(item, str) and item.strip()]
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        result: list[str] = []
        for item in value:
            result.extend(_iter_values(item))
        return result
    return []


def _is_relevant_dependency(value: str) -> bool:
    return normalize_text(value) not in {_strip_accents(item).lower() for item in _NOISE_DEPENDENCIES}


def _gold_claims(gold: Mapping[str, Any], prompt: str) -> list[dict[str, Any]]:
    candidates = gold.get("field_candidates")
    if not isinstance(candidates, Mapping):
        return []
    claims: list[dict[str, Any]] = []
    for field, raw_value in candidates.items():
        if field == "datos_criticos":
            continue
        values: list[tuple[str, str]] = []
        if isinstance(raw_value, Mapping):
            values = [(str(key), value) for key, value in raw_value.items() if isinstance(value, str)]
        else:
            values = [(str(index), value) for index, value in enumerate(_iter_values(raw_value))]
        for index, value in values:
            if field == "dependencia" and not _is_relevant_dependency(value):
                continue
            disclosure = token_recall(value, prompt)
            claims.append(
                {
                    "id": f"{field}:{index}",
                    "field": field,
                    "value": value,
                    "prompt_recall": round(disclosure, 6),
                    "disclosed": disclosure >= 0.42,
                    "critical": field in {"organismo", "objeto", "fecha_plazo_vigencia", "normas_citadas", "articulos_resolutivos"},
                }
            )
    return claims


def _claim_match(claim: Mapping[str, Any], candidate_text: str, candidate_typed: set[str]) -> bool:
    field = str(claim["field"])
    value = str(claim["value"])
    if re.search(r"\b(?:salvo|excepto|except[uú]a|exceptuando)\b", _strip_accents(value), re.IGNORECASE) and not re.search(r"\b(?:salvo|excepto|exceptua|exceptuando)\b", _strip_accents(candidate_text), re.IGNORECASE):
        return False
    if field == "normas_citadas":
        expected = extract_typed_claims(value)
        return bool(expected & candidate_typed) or token_recall(value, candidate_text) >= 0.85
    if field == "fecha_plazo_vigencia":
        expected = extract_typed_claims(value)
        return bool(expected & candidate_typed) or token_recall(value, candidate_text) >= 0.8
    if field == "articulos_resolutivos":
        article_number = f"articulo:{claim['id'].split(':', 1)[1]}"
        return article_number in candidate_typed and token_recall(value, candidate_text) >= 0.42
    if field == "dependencia":
        return normalize_text(value) in normalize_text(candidate_text) or token_recall(value, candidate_text) >= 0.75
    return token_recall(value, candidate_text) >= 0.42


def _typed_mismatch(expected_typed: set[str], candidate_typed: set[str]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for prefix in ("norma:", "fecha:", "plazo:", "jurisdiccion:", "expediente:", "monto:", "dni:"):
        expected = {item for item in expected_typed if item.startswith(prefix)}
        candidate = {item for item in candidate_typed if item.startswith(prefix)}
        if not expected or not candidate:
            continue
        if expected.isdisjoint(candidate):
            items.append({"kind": prefix[:-1], "expected": ", ".join(sorted(expected)), "candidate": ", ".join(sorted(candidate))})
    return items


def _polarity_contradictions(gold_text: str, candidate_text: str) -> list[dict[str, str]]:
    if not gold_text or not candidate_text:
        return []
    gold_text = _strip_accents(gold_text)
    candidate_text = _strip_accents(candidate_text)
    shared = _tokens(gold_text) & _tokens(candidate_text)
    if len(shared) < 2:
        return []
    result: list[dict[str, str]] = []
    for allowed, forbidden in _POLARITY_PAIRS:
        if allowed.search(gold_text) and forbidden.search(candidate_text):
            result.append({"kind": "polarity", "expected": allowed.pattern, "candidate": forbidden.pattern})
    gold_negated = re.search(r"\bno\s+(?:se\s+)?(autoriza|permite|debe|puede|podra|debera)\b", gold_text, re.IGNORECASE)
    candidate_negated = re.search(r"\bno\s+(?:se\s+)?(autoriza|permite|debe|puede|podra|debera)\b", candidate_text, re.IGNORECASE)
    if gold_negated and not candidate_negated:
        result.append({"kind": "negation", "expected": gold_negated.group(0), "candidate": "affirmative"})
    elif candidate_negated and not gold_negated:
        result.append({"kind": "negation", "expected": "affirmative", "candidate": candidate_negated.group(0)})
    return result


def _citation_ids(value: Any) -> set[str]:
    ids: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in {"citation_ids", "citation_id"}:
                if isinstance(item, str):
                    ids.update(_CITATION_RE.findall(item.upper()))
                elif isinstance(item, Sequence):
                    ids.update(str(part).upper() for part in item if _CITATION_RE.fullmatch(str(part)))
            elif key != "sources":
                ids.update(_citation_ids(item))
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        for item in value:
            ids.update(_citation_ids(item))
    return ids


def _source_metrics(case: Mapping[str, Any], output: Any) -> dict[str, Any]:
    retrieved = case.get("sources")
    retrieved_ids = {
        str(item.get("citation_id") or item.get("citationId")).upper()
        for item in retrieved or []
        if isinstance(item, Mapping) and (item.get("citation_id") or item.get("citationId"))
    }
    cited = _citation_ids(output)
    traceable = cited & retrieved_ids
    text_available = any(
        isinstance(item, Mapping) and any(item.get(key) for key in ("text", "chunk_text", "content"))
        for item in retrieved or []
    )
    selected_raw = case.get("selected")
    selected_count = (
        int(selected_raw)
        if isinstance(selected_raw, int) and not isinstance(selected_raw, bool)
        else len(selected_raw)
        if isinstance(selected_raw, Sequence) and not isinstance(selected_raw, (str, bytes, bytearray))
        else None
    )
    catalog = output.get("sources") if isinstance(output, Mapping) else None
    catalog_external_ids = {
        str(item.get("external_id"))
        for item in catalog or []
        if isinstance(item, Mapping) and item.get("external_id") is not None
    }
    case_external_id = case.get("external_id")
    return {
        "status": CALCULATED if text_available else NOT_RECONSTRUCTABLE,
        "reason": None if text_available else "historical_sources_contain_ids_and_scores_but_not_chunk_text",
        "citation_traceability": len(traceable) / len(cited) if cited else 0.0,
        "cited_ids": sorted(cited),
        "traceable_ids": sorted(traceable),
        "retrieved_count": len(retrieved_ids),
        "selected_count": selected_count,
        "candidate_reference_alignment": (
            1.0 if str(case_external_id) in catalog_external_ids else 0.0
            if case_external_id is not None and catalog_external_ids
            else None
        ),
        "candidate_source_external_ids": sorted(catalog_external_ids),
        "text_available": text_available,
    }


def evaluate_case(case: Mapping[str, Any], gold: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate one historical case and return all V2 core dimensions."""

    case_input = case.get("input") if isinstance(case.get("input"), Mapping) else {}
    prompt = str(case_input.get("prompt_text") or case.get("prompt") or "")
    output = case.get("output") if case.get("output") is not None else case.get("candidate")
    candidate_text = flatten_output(output)
    candidate_typed = extract_typed_claims(candidate_text) | _structured_article_claims(output)
    gold_claims = _gold_claims(gold, prompt)
    disclosed = [claim for claim in gold_claims if claim["disclosed"]]
    matched: list[dict[str, Any]] = []
    omissions: list[dict[str, Any]] = []
    for claim in disclosed:
        item = dict(claim)
        item["matched"] = _claim_match(claim, candidate_text, candidate_typed)
        (matched if item["matched"] else omissions).append(item)

    expected_typed = extract_typed_claims(" ".join(str(item["value"]) for item in disclosed))
    contradictions = _typed_mismatch(expected_typed, candidate_typed)
    contradictions.extend(_polarity_contradictions(prompt, candidate_text))
    gold_fact_text = " ".join(
        str(item.get("text", ""))
        for item in gold.get("facts", [])
        if isinstance(item, Mapping)
    )
    allowed_typed = (
        extract_typed_claims(prompt)
        | extract_typed_claims(" ".join(str(item["value"]) for item in gold_claims))
        | extract_typed_claims(gold_fact_text)
        | _gold_typed_claims(gold)
    )
    raw_articles = gold.get("field_candidates", {}).get("articulos_resolutivos", {}) if isinstance(gold.get("field_candidates"), Mapping) else {}
    if isinstance(raw_articles, Mapping):
        allowed_typed.update(f"articulo:{int(number)}" for number in raw_articles if str(number).isdigit())
    unsupported_typed = sorted(candidate_typed - allowed_typed)
    unsupported = [{"kind": "unsupported_typed_claim", "text": value, "severity": "critical"} for value in unsupported_typed]
    for kind, pattern in _FORBIDDEN_PATTERNS:
        match = pattern.search(_strip_accents(candidate_text))
        if match:
            unsupported.append({"kind": kind, "text": match.group(0), "severity": "critical"})

    fields: dict[str, dict[str, Any]] = {}
    for field in sorted({str(item["field"]) for item in gold_claims}):
        items = [item for item in gold_claims if item["field"] == field]
        visible = [item for item in items if item["disclosed"]]
        field_matches = [item for item in matched if item["field"] == field]
        fields[field] = {
            "status": "NOT_EXPECTED" if not visible else ("PASS" if len(field_matches) == len(visible) else "FAIL"),
            "expected": len(visible),
            "matched": len(field_matches),
            "prompt_disclosed": len(visible),
        }

    source = _source_metrics(case, output)
    critical_omissions = [item for item in omissions if item["critical"]]
    critical_contradictions = [item for item in contradictions]
    legal_pass = not critical_omissions and not critical_contradictions and not unsupported and all(
        item["status"] in {"PASS", "NOT_EXPECTED"} for item in fields.values()
    )
    reasons: list[str] = []
    if critical_omissions:
        reasons.append(f"critical_omissions={len(critical_omissions)}")
    if critical_contradictions:
        reasons.append(f"critical_contradictions={len(critical_contradictions)}")
    if unsupported:
        reasons.append(f"unsupported_additions={len(unsupported)}")
    if not legal_pass and not reasons:
        reasons.append("critical_field_failure")
    case_id = case.get("external_id") or case_input.get("external_id") or case.get("case_number")
    return {
        "case_id": str(case_id or ""),
        "external_id": case_input.get("external_id"),
        "reference_pdf": gold.get("reference_pdf"),
        "reference_sha256": gold.get("reference_sha256"),
        "prompt_coverage": {
            "status": CALCULATED if gold_claims else NOT_RECONSTRUCTABLE,
            "total_gold_claims": len(gold_claims),
            "disclosed_claims": len(disclosed),
            "rate": len(disclosed) / len(gold_claims) if gold_claims else None,
        },
        "atomic_claims": {
            "status": CALCULATED if disclosed else NOT_RECONSTRUCTABLE,
            "expected": len(disclosed),
            "matched": len(matched),
            "omitted": len(omissions),
            "recall": len(matched) / len(disclosed) if disclosed else None,
        },
        "critical_fields": {
            "status": CALCULATED if fields else NOT_RECONSTRUCTABLE,
            "all_correct": all(item["status"] in {"PASS", "NOT_EXPECTED"} for item in fields.values()),
            "fields": fields,
        },
        "contradictions": {
            "status": CALCULATED,
            "count": len(contradictions),
            "critical_count": len(critical_contradictions),
            "items": contradictions,
        },
        "omissions": {
            "status": CALCULATED,
            "count": len(omissions),
            "critical_count": len(critical_omissions),
            "items": omissions,
        },
        "unsupported_additions": {
            "status": CALCULATED,
            "count": len(unsupported),
            "critical_count": len(unsupported),
            "items": unsupported,
        },
        "source_faithfulness": source,
        "retrieval": {
            "status": source["status"],
            "reason": source["reason"],
            "retrieved_count": source["retrieved_count"],
            "selected_count": source["selected_count"],
        },
        "legal_pass": legal_pass,
        "legal_pass_reasons": reasons,
    }
