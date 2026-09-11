"""Pure helpers for configurable IMI LEG templates."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import date
from io import BytesIO
from typing import Any

from docx import Document
from docx.table import Table

from legal_ai.domain.docx_placeholders import normalize_key
from legal_ai.domain.errors import TemplateImportInvalidError

MARKER_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*\}\}")
PLACEHOLDER_RE = re.compile(r"(?:_{4,}|\[([^\]\n]{2,80})\]|<<([^>\n]{2,80})>>)")
FIELD_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
# Fecha textual con segmentos (____/____/______) que debe agruparse en un campo.
_DATE_BLANK_RE = re.compile(r"_{2,}\s*[/\-.]\s*_{2,}(?:\s*[/\-.]\s*_{2,})+")
# Etiqueta de la misma línea: "Nombre: ____", "Monto: $ ____".
_LABEL_PREFIX_RE = re.compile(
    r"([A-Za-zÁÉÍÓÚÜÑáéíóúüñ]"
    r"[A-Za-z0-9ÁÉÍÓÚÜÑáéíóúüñ _.\-]{0,60})"
    r"\s*:\s*[$€£¥\s]*$"
)
_WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _value(item: object) -> dict[str, Any]:
    if isinstance(item, Mapping):
        return dict(item)
    model_dump = getattr(item, "model_dump", None)
    if callable(model_dump):
        return dict(model_dump(mode="json"))
    return {}


def _text(value: object) -> str:
    return "" if value is None else str(value)


def _valid_cuit(value: object) -> bool:
    digits = re.sub(r"[-\s]", "", str(value))
    if not re.fullmatch(r"\d{11}", digits):
        return False
    weights = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
    check_digit = 11 - sum(
        int(digit) * weight
        for digit, weight in zip(digits[:10], weights, strict=True)
    ) % 11
    if check_digit == 11:
        check_digit = 0
    elif check_digit == 10:
        check_digit = 9
    return check_digit == int(digits[-1])


def body_to_blocks(body: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for _index, raw_line in enumerate(body.splitlines(), start=1):
        content = raw_line.strip()
        if not content:
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", content)
        if heading:
            blocks.append(
                {
                    "id": f"block-{len(blocks) + 1}",
                    "type": "heading",
                    "content": heading.group(2),
                    "level": len(heading.group(1)),
                }
            )
        elif re.match(r"^[-*]\s+", content):
            blocks.append(
                {
                    "id": f"block-{len(blocks) + 1}",
                    "type": "list",
                    "content": re.sub(r"^[-*]\s+", "", content),
                }
            )
        else:
            blocks.append(
                {
                    "id": f"block-{len(blocks) + 1}",
                    "type": "paragraph",
                    "content": content,
                }
            )
    return blocks


def marker_keys(body: str) -> list[str]:
    seen: set[str] = set()
    keys: list[str] = []
    for match in MARKER_RE.finditer(body):
        key = match.group(1)
        if key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


def fields_from_markers(body: str) -> list[dict[str, Any]]:
    return [
        {
            "key": key,
            "label": key.replace(".", " ").replace("_", " ").title(),
            "type": "text",
            "required": True,
            "order": index,
        }
        for index, key in enumerate(marker_keys(body))
    ]


def _bound(value: object, field_type: str | None) -> float | int | None:
    if value is None or value == "":
        return None
    if field_type == "date":
        try:
            return date.fromisoformat(str(value)).toordinal()
        except ValueError:
            return None
    if field_type in {"number", "currency"}:
        raw = str(value).strip().replace("$", "").replace(" ", "")
        if "," in raw:
            raw = raw.replace(".", "").replace(",", ".")
        try:
            return float(raw)
        except ValueError:
            return None
    return None


def validate_definition(
    *,
    name: str,
    body: str,
    fields: Sequence[object],
    rules: Sequence[object],
    blocks: Sequence[object] | None = None,
) -> list[str]:
    errors: list[str] = []
    if not name.strip():
        errors.append("El nombre de la plantilla es obligatorio.")
    if not body.strip():
        errors.append("El contenido de la plantilla es obligatorio.")

    field_values = [_value(item) for item in fields]
    keys: set[str] = set()
    field_types: dict[str, str] = {}
    for field in field_values:
        key = _text(field.get("key"))
        if not FIELD_KEY_RE.fullmatch(key):
            errors.append(f'El identificador "{key or "vacío"}" no es válido.')
        if key in keys:
            errors.append(f'El identificador "{key}" está repetido.')
        keys.add(key)
        field_types[key] = _text(field.get("type"))
        if field.get("type") == "select" and not field.get("options"):
            errors.append(f'El campo "{field.get("label") or key}" necesita opciones.')

    referenced = set(marker_keys(body))
    for key in referenced - keys:
        errors.append(f'El contenido usa "{key}" pero no existe ese campo.')

    block_values = [_value(item) for item in (blocks or body_to_blocks(body))]
    block_ids = {str(item.get("id")) for item in block_values}
    if len(block_ids) != len(block_values):
        errors.append("Los identificadores de bloque deben ser únicos.")

    dependencies: dict[str, str] = {}
    for rule in (_value(item) for item in rules):
        rule_type = rule.get("type")
        target = rule.get("field")
        source = rule.get("source_field")
        if rule_type != "visibility" and not target:
            errors.append("Cada regla debe indicar un campo destino.")
        if target and target not in keys:
            errors.append(f'Una regla apunta al campo inexistente "{target}".')
        if rule_type == "visibility" and not rule.get("block_id"):
            errors.append("Una regla de visibilidad debe indicar un bloque.")
        if rule_type == "visibility" and rule.get("block_id") not in block_ids:
            errors.append(f'El bloque "{rule.get("block_id")}" no existe.')
        if rule_type == "derived":
            if not rule.get("derive"):
                errors.append("Una regla calculada debe indicar el cálculo.")
            if not source:
                errors.append("Una regla calculada debe indicar un campo de origen.")
            elif source not in keys:
                errors.append(
                    f'Una regla apunta al campo de origen inexistente "{source}".'
                )
            if target and source:
                dependencies[str(target)] = str(source)
        min_length = rule.get("min_length")
        max_length = rule.get("max_length")
        if (
            min_length is not None
            and max_length is not None
            and min_length > max_length
        ):
            errors.append("El mínimo de texto no puede superar al máximo.")
        min_value = _bound(rule.get("min_value"), field_types.get(str(target)))
        max_value = _bound(rule.get("max_value"), field_types.get(str(target)))
        if min_value is not None and max_value is not None and min_value > max_value:
            errors.append("El mínimo no puede superar al máximo.")
        for condition in (_value(item) for item in rule.get("conditions") or []):
            condition_field = condition.get("field")
            if condition_field not in keys:
                errors.append(
                    f'Una condición apunta al campo inexistente "{condition_field}".'
                )
            if condition.get("operator") not in {
                "present",
                "not_present",
            } and condition.get("value") in (None, ""):
                errors.append("Las comparaciones deben indicar un valor.")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(key: str) -> bool:
        if key in visiting:
            return True
        if key in visited:
            return False
        visiting.add(key)
        circular = key in dependencies and visit(dependencies[key])
        visiting.remove(key)
        visited.add(key)
        return circular

    if any(visit(key) for key in dependencies):
        errors.append("Las reglas calculadas no pueden tener dependencias circulares.")
    return list(dict.fromkeys(errors))


def _condition_matches(
    condition: Mapping[str, Any],
    values: Mapping[str, Any],
    field_types: Mapping[str, str],
) -> bool:
    field = str(condition.get("field", ""))
    actual = values.get(field)
    operator = condition.get("operator")
    present = actual is not None and actual != ""
    if operator == "present":
        return present
    if operator == "not_present":
        return not present
    expected = condition.get("value")
    if operator in {"greater_than", "less_than", "greater_or_equal", "less_or_equal"}:
        actual_bound = _bound(actual, field_types.get(field))
        expected_bound = _bound(expected, field_types.get(field))
        if actual_bound is None or expected_bound is None:
            return False
        return {
            "greater_than": actual_bound > expected_bound,
            "less_than": actual_bound < expected_bound,
            "greater_or_equal": actual_bound >= expected_bound,
            "less_or_equal": actual_bound <= expected_bound,
        }[operator]
    if operator == "equals":
        return actual == expected or str(actual) == str(expected)
    if operator == "not_equals":
        return not (actual == expected or str(actual) == str(expected))
    return False


def _rules_apply(
    rule: Mapping[str, Any], values: Mapping[str, Any], field_types: Mapping[str, str]
) -> bool:
    conditions = rule.get("conditions") or []
    if not conditions:
        return True
    results = [
        _condition_matches(_value(condition), values, field_types)
        for condition in conditions
    ]
    return all(results) if rule.get("match", "all") == "all" else any(results)


def normalize_values(
    fields: Sequence[object], values: Mapping[str, Any]
) -> dict[str, Any]:
    result = dict(values)
    for field in (_value(item) for item in fields):
        key = str(field.get("key", ""))
        raw = result.get(key)
        if raw is None or raw == "":
            continue
        field_type = field.get("type")
        if field_type in {"number", "currency"} and isinstance(raw, str):
            parsed = _bound(raw, field_type)
            if parsed is not None:
                result[key] = int(parsed) if parsed.is_integer() else parsed
        elif field_type == "boolean" and isinstance(raw, str):
            normalized = raw.strip().lower()
            if normalized in {"true", "1", "si", "sí"}:
                result[key] = True
            elif normalized in {"false", "0", "no"}:
                result[key] = False
    return result


def _amount_words(value: object) -> str:
    try:
        number = int(float(str(value).replace(".", "").replace(",", ".")))
    except ValueError:
        return str(value)
    small = [
        "cero",
        "uno",
        "dos",
        "tres",
        "cuatro",
        "cinco",
        "seis",
        "siete",
        "ocho",
        "nueve",
        "diez",
        "once",
        "doce",
        "trece",
        "catorce",
        "quince",
    ]
    if 0 <= number < len(small):
        return small[number]
    if number == 100:
        return "cien"
    if number < 100:
        tens = [
            "",
            "",
            "veinte",
            "treinta",
            "cuarenta",
            "cincuenta",
            "sesenta",
            "setenta",
            "ochenta",
            "noventa",
        ]
        return tens[number // 10] + (f" y {small[number % 10]}" if number % 10 else "")
    if number < 1000:
        hundreds = [
            "",
            "ciento",
            "doscientos",
            "trescientos",
            "cuatrocientos",
            "quinientos",
            "seiscientos",
            "setecientos",
            "ochocientos",
            "novecientos",
        ]
        return hundreds[number // 100] + (
            f" {number_to_words(number % 100)}" if number % 100 else ""
        )
    if number < 1_000_000:
        thousands = number // 1000
        prefix = "mil" if thousands == 1 else f"{number_to_words(thousands)} mil"
        return prefix + (f" {number_to_words(number % 1000)}" if number % 1000 else "")
    return str(number)


def number_to_words(number: int) -> str:
    return _amount_words(number)


def resolve_values(
    fields: Sequence[object], rules: Sequence[object], values: Mapping[str, Any]
) -> dict[str, Any]:
    result = normalize_values(fields, values)
    for _ in range(max(1, len(fields))):
        changed = False
        for rule in (_value(item) for item in rules):
            if (
                rule.get("type") != "derived"
                or not rule.get("field")
                or not rule.get("source_field")
            ):
                continue
            source = result.get(str(rule["source_field"]))
            if source in (None, ""):
                continue
            next_value: str | None = None
            if rule.get("derive") == "amount_words":
                next_value = _amount_words(source)
            elif rule.get("derive") == "year_from_date":
                next_value = (
                    str(source)[:4] if re.match(r"^\d{4}-", str(source)) else None
                )
            if next_value is not None and result.get(str(rule["field"])) != next_value:
                result[str(rule["field"])] = next_value
                changed = True
        if not changed:
            break
    return result


def validate_values(
    fields: Sequence[object], rules: Sequence[object], values: Mapping[str, Any]
) -> list[str]:
    field_values = [_value(item) for item in fields]
    field_types = {
        str(field.get("key")): str(field.get("type", "text")) for field in field_values
    }
    resolved = resolve_values(fields, rules, values)
    errors: list[str] = []
    for field in field_values:
        key = str(field.get("key", ""))
        value = resolved.get(key)
        if field.get("required") and not field.get("read_only") and value in (None, ""):
            errors.append(f'Falta completar "{field.get("label") or key}".')
        if field.get("type") == "select" and value not in (None, ""):
            options = {
                str(_value(option).get("value"))
                for option in field.get("options") or []
            }
            if str(value) not in options:
                errors.append(
                    f'El valor de "{field.get("label") or key}" no está entre '
                    "las opciones."
                )
    for rule in (_value(item) for item in rules):
        if rule.get("type") != "validation" or not _rules_apply(
            rule, resolved, field_types
        ):
            continue
        key = str(rule.get("field", ""))
        value = resolved.get(key)
        if value in (None, ""):
            continue
        message = str(rule.get("message") or f'El campo "{key}" no cumple la regla.')
        if rule.get("min_length") is not None and len(str(value)) < int(
            rule["min_length"]
        ):
            errors.append(message)
        if rule.get("max_length") is not None and len(str(value)) > int(
            rule["max_length"]
        ):
            errors.append(message)
        field_type = field_types.get(key)
        actual = _bound(value, field_type)
        lower = _bound(rule.get("min_value"), field_type)
        upper = _bound(rule.get("max_value"), field_type)
        if lower is not None and (actual is None or actual < lower):
            errors.append(message)
        if upper is not None and (actual is None or actual > upper):
            errors.append(message)
        if rule.get("format") == "email" and not re.fullmatch(
            r"[^\s@]+@[^\s@]+\.[^\s@]+", str(value)
        ):
            errors.append(message)
        if rule.get("format") == "cuit" and not _valid_cuit(value):
            errors.append(message)
    return list(dict.fromkeys(errors))


def render_template(body: str, values: Mapping[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        value = values.get(key)
        return match.group(0) if value is None or value == "" else str(value)

    return MARKER_RE.sub(replace, body)


def preview_document(
    *,
    name: str,
    document_type: str,
    body: str,
    fields: Sequence[object],
    rules: Sequence[object],
    blocks: Sequence[object] | None,
    values: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str], list[str]]:
    definition_errors = validate_definition(
        name=name, body=body, fields=fields, rules=rules, blocks=blocks
    )
    normalized = resolve_values(fields, rules, values)
    value_errors = validate_values(fields, rules, normalized)
    rendered = render_template(body, normalized)
    source_blocks = [_value(item) for item in (blocks or body_to_blocks(body))]
    hidden: set[str] = set()
    field_types = {
        str(_value(item).get("key")): str(_value(item).get("type", "text"))
        for item in fields
    }
    for rule in (_value(item) for item in rules):
        if (
            rule.get("type") == "visibility"
            and rule.get("block_id")
            and _rules_apply(rule, normalized, field_types)
        ):
            hidden.add(str(rule["block_id"]))
    rendered_blocks = [
        {**block, "content": render_template(str(block.get("content", "")), normalized)}
        for block in source_blocks
        if str(block.get("id")) not in hidden
    ]
    warnings = ["La previsualización no crea expediente ni numeración oficial."]
    document = {
        "schema_version": 1,
        "document_type": document_type,
        "locale": "es-AR",
        "institutional_header": "INSTITUTO DE MODERNIZACIÓN E INNOVACIÓN",
        "title": name,
        "visto": [],
        "considerandos": [],
        "dispositive_intro": "",
        "articles": [],
        "closing": "",
        "authority": "",
        "signature": "",
        "sources": [],
        "warnings": ["BORRADOR NO VINCULANTE; REVISION HUMANA OBLIGATORIA."],
        "blocks": rendered_blocks,
        "content": rendered,
    }
    return document, list(dict.fromkeys([*definition_errors, *value_errors])), warnings


def _slugify_label(label: str) -> str:
    normalized = unicodedata.normalize("NFKD", label.strip())
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9]+", "_", ascii_text.lower()).strip("_")
    if not slug or not FIELD_KEY_RE.fullmatch(slug):
        return ""
    return slug


def normalize_blank_fields(body: str) -> str:
    """Convierte blancos textuales en marcadores ``{{campo}}``.

    Usa la etiqueta de la misma línea ("Nombre: ____" -> "{{nombre}}"),
    agrupa segmentos de fecha en un solo campo, reutiliza la misma clave para
    etiquetas duplicadas, usa fallback estable ``campo_N`` sin etiqueta,
    preserva ``{{variable}}`` existente y no convierte texto normal.
    """

    used: set[str] = set(marker_keys(body))
    label_to_key: dict[str, str] = {}
    fallback_next = 1

    def _key_for_label(raw_label: str) -> str:
        nonlocal fallback_next
        slug = _slugify_label(raw_label) if raw_label else ""
        if not slug:
            while True:
                candidate = f"campo_{fallback_next}"
                fallback_next += 1
                if candidate not in used:
                    used.add(candidate)
                    return candidate
        if slug in label_to_key:
            return label_to_key[slug]
        if slug not in used:
            label_to_key[slug] = slug
            used.add(slug)
            return slug
        # Misma etiqueta que un {{marcador}} ya existente: reutilizar.
        label_to_key[slug] = slug
        return slug

    def _normalize_line(line: str) -> str:
        marker_spans = [m.span() for m in MARKER_RE.finditer(line)]
        date_spans = [m.span() for m in _DATE_BLANK_RE.finditer(line)]
        trailing_blank_start: int | None = None

        def _inside(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
            return any(
                span_start <= start and end <= span_end
                for span_start, span_end in spans
            )

        # Los corchetes y ángulos se reservan para sugerencias, no se convierten
        # automáticamente porque pueden ser referencias legales del documento.
        candidates: list[tuple[int, int, str | None]] = [
            (m.start(), m.end(), None)
            for m in PLACEHOLDER_RE.finditer(line)
            if not (m.group(1) or m.group(2))
            if not _inside(m.start(), m.end(), date_spans)
        ]
        for match in _DATE_BLANK_RE.finditer(line):
            candidates.append((match.start(), match.end(), None))
        candidates.sort(key=lambda item: (item[0], -(item[1] - item[0])))
        # Descarta solapes conservando el primero (fecha agrupada gana).
        selected: list[tuple[int, int, str | None]] = []
        last_end = -1
        for start, end, inner in candidates:
            if start < last_end:
                continue
            selected.append((start, end, inner))
            last_end = end

        # DOCX puede conservar un blanco como espacios finales después de la etiqueta.
        if not selected:
            trailing_blank = re.search(r"[ \t\u00a0]{4,}$", line)
            if trailing_blank and _LABEL_PREFIX_RE.search(
                line[: trailing_blank.start()]
            ):
                selected.append((trailing_blank.start(), trailing_blank.end(), None))
                trailing_blank_start = trailing_blank.start()

        if not selected:
            return line
        pieces: list[str] = []
        cursor = 0
        for start, end, inner in selected:
            if _inside(start, end, marker_spans):
                continue
            inner_label = (inner or "").strip(" _-") if inner is not None else ""
            if inner_label and (set(inner_label) <= {"_"} or inner_label.isdigit()):
                inner_label = ""
            if inner_label:
                raw_label = inner_label
            else:
                prefix = _LABEL_PREFIX_RE.search(line[:start])
                raw_label = prefix.group(1).strip() if prefix else ""
            pieces.append(line[cursor:start])
            if start == trailing_blank_start:
                pieces.append(" ")
            pieces.append("{{" + _key_for_label(raw_label) + "}}")
            cursor = end
        pieces.append(line[cursor:])
        return "".join(pieces)

    return "\n".join(_normalize_line(line) for line in body.split("\n"))


def suggestions_for_body(body: str, fields: Sequence[object]) -> list[dict[str, Any]]:
    known = {str(_value(item).get("key")) for item in fields}
    grouped: dict[str, dict[str, Any]] = {}
    for match in PLACEHOLDER_RE.finditer(body):
        fragment = match.group(0)
        label = (match.group(1) or match.group(2) or "campo").strip(" _-")
        if set(label) <= {"_"} or label.isdigit():
            label = "campo"
        key = re.sub(r"[^A-Za-z0-9]+", "_", label.lower()).strip("_") or "campo"
        if key in known:
            continue
        suffix = 2
        base = key
        while key in grouped:
            key = f"{base}_{suffix}"
            suffix += 1
        item = grouped.setdefault(
            fragment,
            {
                "key": key,
                "label": label.replace("_", " ").title(),
                "type": "text",
                "fragment": fragment,
                "confidence": 0.82,
                "occurrences": [],
            },
        )
        item["occurrences"].append(
            {"start": match.start(), "end": match.end(), "text": fragment}
        )
    return list(grouped.values())


TEMPLATE_EXTRACTOR_VERSION = "docx-parser-v1"


def parser_candidates_to_safe(candidates: Sequence[object]) -> list[dict[str, Any]]:
    """Convert parser candidates to bounded, auditable import candidates."""
    safe: list[dict[str, Any]] = []
    for item in candidates:
        as_dict = getattr(item, "to_safe_dict", None)
        payload = dict(as_dict()) if callable(as_dict) else _value(item)
        key = str(payload.get("normalized_key") or payload.get("key") or "").strip()
        if not key:
            continue
        syntax_value = getattr(item, "syntax", payload.get("syntax", "BLANK"))
        syntax = str(getattr(syntax_value, "value", syntax_value)).upper()
        origin_value = getattr(item, "origin", payload.get("origin", "PARAGRAPH"))
        origin = str(getattr(origin_value, "value", origin_value)).upper()
        kind_value = getattr(item, "field_kind", payload.get("field_kind", "TEXT"))
        field_kind = str(getattr(kind_value, "value", kind_value)).upper()
        original_text = str(getattr(item, "original_text", ""))[:200]
        locations = payload.get("locations", [])
        if not isinstance(locations, list):
            locations = []
        status = (
            "suggested"
            if syntax in {"BLANK", "ELLIPSIS", "COMPLETAR"}
            else "confirmed"
        )
        field_type = {
            "DATE": "date",
            "NUMBER": "number",
            "CURRENCY": "currency",
            "CHECKBOX": "boolean",
        }.get(field_kind, "text")
        key_lower = key.lower()
        if "cuit" in key_lower or "cuil" in key_lower:
            field_type = "text"
        suggested_format = (
            "email"
            if field_kind == "EMAIL" or "email" in key_lower or "correo" in key_lower
            else "cuit"
            if "cuit" in key_lower or "cuil" in key_lower
            else None
        )
        explanation = str(
            getattr(item, "explanation", "")
            or payload.get("explanation")
            or "Candidato detectado por reglas determinísticas."
        )[:500]
        safe.append(
            {
                "key": key,
                "origin": origin,
                "syntax": syntax,
                "confidence": float(
                    getattr(item, "confidence", payload.get("confidence") or 0.5)
                ),
                "field_kind": field_kind,
                "occurrences": int(
                    getattr(item, "occurrences", payload.get("occurrences") or 1)
                ),
                "original_text": original_text or None,
                "fragment": original_text or None,
                "label": key.replace("_", " ").replace(".", " ").title(),
                "type": field_type,
                "format": suggested_format,
                "status": status,
                "explanation": explanation,
                "locations": locations,
            }
        )
    return safe


def suggestions_to_candidates(
    suggestions: Sequence[object],
) -> list[dict[str, Any]]:
    """Convert body suggestions to PII-free import candidates (PDF fallback)."""
    safe: list[dict[str, Any]] = []
    for item in (_value(entry) for entry in suggestions):
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        occurrences = item.get("occurrences") or []
        count = len(occurrences) if isinstance(occurrences, list) else 1
        locations = [
            {
                key: value
                for key, value in occurrence.items()
                if key != "text"
            }
            for occurrence in occurrences
            if isinstance(occurrence, Mapping)
        ]
        candidate_type = str(item.get("type") or "text")
        suggested_format = item.get("format")
        safe.append(
            {
                "key": key,
                "origin": "PARAGRAPH",
                "syntax": "BLANK",
                "confidence": float(item.get("confidence") or 0.55),
                "field_kind": "TEXT",
                "occurrences": max(1, count),
                "original_text": None,
                "fragment": None,
                "label": str(item.get("label") or key),
                "type": candidate_type,
                "format": suggested_format,
                "status": "suggested",
                "explanation": str(
                    item.get("explanation")
                    or "Fragmento ambiguo sugerido para revisión humana."
                )[:500],
                "locations": locations,
            }
        )
    return safe


def _xml_text(element: Any) -> str:
    return "".join(
        node.text or ""
        for node in element.iter()
        if str(node.tag).endswith("}t")
    )


def _append_docx_container(
    container: Any,
    document: Any,
    parts: list[str],
    warnings: list[str],
) -> None:
    for child in container.iterchildren():
        if child.tag.endswith("}p"):
            text = _xml_text(child)
            if text.strip():
                parts.append(text)
        elif child.tag.endswith("}tbl"):
            table = Table(child, document)
            rows = []
            for row_index, row in enumerate(table.rows):
                cells = []
                for col_index, cell in enumerate(row.cells):
                    cells.append(
                        cell.text.strip()
                        or f"{{{{celda_vacia_{row_index + 1}_{col_index + 1}}}}}"
                    )
                rows.append(" | ".join(cells))
            parts.extend(row for row in rows if row.strip())
            warnings.append(
                "El archivo contiene tablas; revisá su representación en el editor."
            )
        elif child.tag.endswith("}sdt"):
            content = child.find(
                ".//w:sdtContent", namespaces={"w": _WORD_NS}
            )
            if content is not None:
                for nested in content.iterchildren():
                    if nested.tag.endswith("}p"):
                        text = _xml_text(nested)
                        if text.strip():
                            parts.append(text)
                    elif nested.tag.endswith("}tbl"):
                        table = Table(nested, document)
                        rows = [
                            " | ".join(
                                cell.text.strip()
                                or (
                                    f"{{{{celda_vacia_{row_index + 1}_"
                                    f"{col_index + 1}}}}}"
                                )
                                for col_index, cell in enumerate(row.cells)
                            )
                            for row_index, row in enumerate(table.rows)
                        ]
                        parts.extend(row for row in rows if row.strip())
                        warnings.append(
                            "El archivo contiene tablas; revisá su representación "
                            "en el editor."
                        )
                if not list(content.iterchildren()):
                    text = _xml_text(content)
                    if text.strip():
                        parts.append(text)

    for text_box in container.findall(
        ".//w:txbxContent", namespaces={"w": _WORD_NS}
    ):
        for paragraph in text_box.findall(".//w:p", namespaces={"w": _WORD_NS}):
            text = _xml_text(paragraph)
            if text.strip():
                parts.append(text)

    for bookmark in container.findall(
        ".//w:bookmarkStart", namespaces={"w": _WORD_NS}
    ):
        name = str(bookmark.get(f"{{{_WORD_NS}}}name", "") or "").strip()
        key = normalize_key(name) if name.lower() != "_goback" else ""
        if key:
            parts.append(f"{{{{{key}}}}}")


def extract_file_content(
    filename: str, content_type: str | None, data: bytes
) -> tuple[str, list[dict[str, Any]], list[str], int]:
    lower_name = filename.lower()
    if lower_name.endswith(".docx") or "wordprocessingml.document" in (
        content_type or ""
    ):
        try:
            document = Document(BytesIO(data))
        except Exception as exc:  # pragma: no cover - library-specific parse failures
            raise TemplateImportInvalidError(
                "El archivo DOCX no se pudo leer.",
                details={"reason": type(exc).__name__},
            ) from exc
        parts: list[str] = []
        warnings: list[str] = []
        _append_docx_container(document.element.body, document, parts, warnings)
        for section in document.sections:
            _append_docx_container(section.header._element, document, parts, warnings)
            _append_docx_container(section.footer._element, document, parts, warnings)
        body = "\n".join(parts)
        body = normalize_blank_fields(body)
        return body, body_to_blocks(body), list(dict.fromkeys(warnings)), 1
    if lower_name.endswith(".pdf") or content_type == "application/pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(BytesIO(data))
            page_text: list[str] = []
            warnings = []
            for index, page in enumerate(reader.pages, start=1):
                text = page.extract_text() or ""
                if not text.strip():
                    warnings.append(
                        f"La página {index} no contiene texto extraíble; requiere "
                        "revisión manual."
                    )
                page_text.append(text.strip())
            body = "\n\n".join(text for text in page_text if text)
            body = normalize_blank_fields(body)
            return (
                body,
                body_to_blocks(body),
                list(dict.fromkeys(warnings)),
                len(reader.pages),
            )
        except TemplateImportInvalidError:
            raise
        except Exception as exc:  # pragma: no cover - library-specific parse failures
            raise TemplateImportInvalidError(
                "El archivo PDF no se pudo leer.",
                details={"reason": type(exc).__name__},
            ) from exc
    raise TemplateImportInvalidError("Solo se admiten archivos DOCX o PDF.")
