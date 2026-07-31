"""Pure normalization functions for domain data."""

from __future__ import annotations

import re

from legal_ai.domain.enums import DocumentType


def normalize_document_number(doc_type: str, value: str) -> str:
    """Normalize document number according to document type.

    Rules:
    - Trim whitespace.
    - Reject empty values.
    - DNI: digits only (0-9).
    - LC, LE, CI, Passport: alphanumeric, uppercase letters.
    - No leading zeros added.
    - No silent character removal.
    """
    normalized = value.strip()
    if not normalized:
        raise ValueError("document_number cannot be empty after trim")

    doc_type_enum = DocumentType(doc_type)

    if doc_type_enum == DocumentType.DNI:
        if not re.fullmatch(r"[0-9]+", normalized):
            raise ValueError("DNI must contain only digits")
        return normalized

    # LC, LE, CI, Passport: alphanumeric, uppercase
    if not re.fullmatch(r"[A-Za-z0-9]+", normalized):
        raise ValueError(f"{doc_type} must contain only alphanumeric characters")
    return normalized.upper()


def normalize_cuil(value: str) -> str:
    """Normalize CUIL value.

    Rules:
    - Trim whitespace.
    - Remove hyphens and spaces.
    - Must be exactly 11 digits.
    """
    normalized = value.strip()
    normalized = normalized.replace("-", "").replace(" ", "")

    if not re.fullmatch(r"[0-9]+", normalized):
        raise ValueError("CUIL must contain only digits")

    if len(normalized) != 11:
        raise ValueError("CUIL must be exactly 11 digits")

    return normalized


def normalize_email(value: str) -> str:
    """Normalize email value.

    Rules:
    - Trim whitespace.
    - Lowercase.
    """
    return value.strip().lower()


def normalize_phone(value: str) -> str:
    """Normalize phone value.

    Rules:
    - Trim whitespace.
    - Remove internal spaces.
    """
    return value.strip().replace(" ", "")


def normalize_text(value: str) -> str:
    """Normalize text value.

    Rules:
    - Trim whitespace.
    - Reject empty values.
    """
    normalized = value.strip()
    if not normalized:
        raise ValueError("text cannot be empty after trim")
    return normalized
