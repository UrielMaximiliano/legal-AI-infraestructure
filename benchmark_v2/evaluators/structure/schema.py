"""Small, dependency-free JSON Schema helpers for structural evaluation.

The benchmark evaluator deliberately keeps schema validation local.  The
application has its own domain validators, while this package needs to score
stored outputs in an environment where optional JSON Schema packages may not
be installed.  The implementation covers the JSON Schema keywords used by
the benchmark contracts (objects, arrays, scalar constraints, ``$ref`` and
the composition keywords) and reports paths rather than raising for ordinary
validation failures.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any
from urllib.parse import urlparse


JSONSchema = Mapping[str, Any]


class SchemaError(ValueError):
    """Raised when a schema cannot be used as a JSON object."""


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _json_type_matches(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "object":
        return isinstance(value, Mapping)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return _is_number(value) and math.isfinite(float(value))
    return True


def _resolve_ref(root: JSONSchema, reference: str) -> Mapping[str, Any]:
    if not reference.startswith("#/"):
        raise SchemaError(f"unsupported JSON Schema reference: {reference!r}")
    current: Any = root
    for part in reference[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, Mapping) or part not in current:
            raise SchemaError(f"unresolved JSON Schema reference: {reference!r}")
        current = current[part]
    if not isinstance(current, Mapping):
        raise SchemaError(f"JSON Schema reference is not an object: {reference!r}")
    return current


def _format_is_valid(value: str, fmt: str) -> bool:
    if fmt == "date":
        try:
            date.fromisoformat(value)
        except ValueError:
            return False
        return True
    if fmt == "date-time":
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        return True
    if fmt in {"uri", "uri-reference"}:
        parsed = urlparse(value)
        return bool(parsed.scheme) if fmt == "uri" else True
    # Unknown formats are annotations in JSON Schema and should not make a
    # score environment-dependent.
    return True


def _unique_json_values(values: Sequence[Any]) -> bool:
    encoded: set[str] = set()
    for value in values:
        try:
            token = json.dumps(
                value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError):
            return False
        if token in encoded:
            return False
        encoded.add(token)
    return True


def _validate(value: Any, schema: Mapping[str, Any], root: JSONSchema, path: str) -> list[str]:
    errors: list[str] = []

    if "$ref" in schema:
        try:
            referenced = _resolve_ref(root, str(schema["$ref"]))
        except SchemaError as exc:
            return [f"{path or '$'}: {exc}"]
        errors.extend(_validate(value, referenced, root, path))

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path or '$'} must equal {schema['const']!r}")
    if "enum" in schema:
        allowed = schema["enum"]
        if not isinstance(allowed, Sequence) or isinstance(allowed, (str, bytes)):
            errors.append(f"{path or '$'} has an invalid enum")
        elif value not in allowed:
            errors.append(f"{path or '$'} must be one of {list(allowed)!r}")

    expected_type = schema.get("type")
    if expected_type is not None:
        types = (
            list(expected_type)
            if isinstance(expected_type, Sequence) and not isinstance(expected_type, str)
            else [expected_type]
        )
        if not any(_json_type_matches(value, str(item)) for item in types):
            errors.append(f"{path or '$'} must be of type {types!r}")
            return errors

    if isinstance(value, Mapping):
        properties = schema.get("properties", {})
        if not isinstance(properties, Mapping):
            errors.append(f"{path or '$'} has invalid properties")
            properties = {}
        required = schema.get("required", [])
        if isinstance(required, Sequence) and not isinstance(required, (str, bytes)):
            for key in required:
                if key not in value:
                    errors.append(f"{path or '$'} missing required property {key!r}")
        for key, child_schema in properties.items():
            if key in value and isinstance(child_schema, Mapping):
                child_path = f"{path}.{key}" if path else str(key)
                errors.extend(_validate(value[key], child_schema, root, child_path))
        additional = schema.get("additionalProperties", True)
        if additional is False:
            unknown = set(value) - set(properties)
            errors.extend(
                f"{path or '$'} has unexpected property {key!r}"
                for key in sorted(unknown, key=str)
            )
        elif isinstance(additional, Mapping):
            for key, item in value.items():
                if key not in properties:
                    child_path = f"{path}.{key}" if path else str(key)
                    errors.extend(_validate(item, additional, root, child_path))

    if isinstance(value, list):
        min_items = schema.get("minItems")
        max_items = schema.get("maxItems")
        if isinstance(min_items, int) and len(value) < min_items:
            errors.append(f"{path or '$'} must contain at least {min_items} items")
        if isinstance(max_items, int) and len(value) > max_items:
            errors.append(f"{path or '$'} must contain at most {max_items} items")
        if schema.get("uniqueItems") is True and not _unique_json_values(value):
            errors.append(f"{path or '$'} must contain unique items")
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(value):
                errors.extend(_validate(item, item_schema, root, f"{path or '$'}[{index}]"))

    if isinstance(value, str):
        min_length = schema.get("minLength")
        max_length = schema.get("maxLength")
        if isinstance(min_length, int) and len(value) < min_length:
            errors.append(f"{path or '$'} must have at least {min_length} characters")
        if isinstance(max_length, int) and len(value) > max_length:
            errors.append(f"{path or '$'} must have at most {max_length} characters")
        pattern = schema.get("pattern")
        if isinstance(pattern, str):
            try:
                matched = re.search(pattern, value) is not None
            except re.error as exc:
                errors.append(f"{path or '$'} has invalid pattern: {exc}")
                matched = True
            if not matched:
                errors.append(f"{path or '$'} does not match pattern {pattern!r}")
        fmt = schema.get("format")
        if isinstance(fmt, str) and not _format_is_valid(value, fmt):
            errors.append(f"{path or '$'} is not a valid {fmt}")

    if _is_number(value):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, (int, float)) and value < minimum:
            errors.append(f"{path or '$'} must be >= {minimum}")
        if isinstance(maximum, (int, float)) and value > maximum:
            errors.append(f"{path or '$'} must be <= {maximum}")

    for composition in ("allOf", "anyOf", "oneOf"):
        alternatives = schema.get(composition)
        if not isinstance(alternatives, Sequence) or isinstance(alternatives, (str, bytes)):
            continue
        matches = [
            not _validate(value, option, root, path)
            for option in alternatives
            if isinstance(option, Mapping)
        ]
        if composition == "allOf" and not all(matches):
            errors.append(f"{path or '$'} does not satisfy allOf")
        elif composition == "anyOf" and not any(matches):
            errors.append(f"{path or '$'} does not satisfy anyOf")
        elif composition == "oneOf" and sum(matches) != 1:
            errors.append(f"{path or '$'} does not satisfy exactly one oneOf option")

    if isinstance(schema.get("not"), Mapping) and not _validate(
        value, schema["not"], root, path
    ):
        errors.append(f"{path or '$'} must not match the not schema")
    return errors


def validate_json_schema(value: Any, schema: JSONSchema) -> list[str]:
    """Return deterministic validation errors for ``value`` against ``schema``."""

    if not isinstance(schema, Mapping):
        raise SchemaError("JSON Schema must be an object")
    return _validate(value, schema, schema, "")


def is_schema_valid(value: Any, schema: JSONSchema) -> bool:
    """Return whether ``value`` satisfies ``schema``."""

    return not validate_json_schema(value, schema)


def assert_schema_valid(value: Any, schema: JSONSchema) -> None:
    """Raise ``SchemaError`` with the first useful contract violation."""

    errors = validate_json_schema(value, schema)
    if errors:
        raise SchemaError("; ".join(errors))


def required_paths(schema: JSONSchema, prefix: str = "") -> tuple[str, ...]:
    """Extract required object paths for completeness scoring."""

    if not isinstance(schema, Mapping):
        return ()
    paths: list[str] = []
    required = schema.get("required", ())
    if isinstance(required, Sequence) and not isinstance(required, (str, bytes)):
        for field in required:
            path = f"{prefix}.{field}" if prefix else str(field)
            paths.append(path)
    properties = schema.get("properties", {})
    if isinstance(properties, Mapping):
        for key, child in properties.items():
            if isinstance(child, Mapping):
                child_prefix = f"{prefix}.{key}" if prefix else str(key)
                paths.extend(required_paths(child, child_prefix))
    return tuple(dict.fromkeys(paths))


# The contract is also useful to callers evaluating the structured RAG draft
# without importing the application package.  It intentionally mirrors the
# public fields only; semantic checks remain the application's responsibility.
RAG_STRUCTURED_DRAFT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "urn:benchmark-v2:rag-structured-draft:v1",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version", "title", "visto", "considerandos",
        "dispositive_intro", "articles", "closing", "authority", "signature",
        "sources", "warnings",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "title": {"type": "string", "minLength": 1},
        "visto": {"type": "array", "minItems": 1},
        "considerandos": {"type": "array", "minItems": 1},
        "dispositive_intro": {"type": "string", "minLength": 1},
        "articles": {"type": "array", "minItems": 1},
        "closing": {"type": "string", "minLength": 1},
        "authority": {"type": "string", "minLength": 1},
        "signature": {"type": "string", "minLength": 1},
        "sources": {"type": "array", "minItems": 1},
        "warnings": {"type": "array", "minItems": 1},
    },
}


__all__ = [
    "JSONSchema",
    "RAG_STRUCTURED_DRAFT_SCHEMA",
    "SchemaError",
    "assert_schema_valid",
    "is_schema_valid",
    "required_paths",
    "validate_json_schema",
]
