"""Allowlisted, deterministic query construction for RAG."""

from __future__ import annotations

import re
from dataclasses import dataclass

from legal_ai.domain.rag import sha256_text

_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SENSITIVE_RE = re.compile(
    r"authorization|bearer|token|embedding|vector|prompt|raw[_ ]?content|"
    r"normalized[_ ]?content|storage[_ ]?path|query",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class RagQuery:
    text: str
    query_hash: str
    filters: dict[str, str]


class RagQueryBuilder:
    """Build only from validated scalar fields and fixed corpus policy."""

    def __init__(self, document_subtype: str = "designacion_transitoria") -> None:
        if document_subtype not in {"designacion_transitoria", "decreto"}:
            raise ValueError("RAG_DOCUMENT_SUBTYPE_INVALID")
        self._document_subtype = document_subtype

    def build(
        self,
        *,
        case_file: dict[str, str] | None = None,
        template: dict[str, str] | None = None,
        variables: dict[str, str] | None = None,
        organization: str | None = None,
        language: str = "es",
    ) -> RagQuery:
        values: list[str] = []
        for group in (case_file or {}, template or {}, variables or {}):
            for key, value in sorted(group.items()):
                if not _KEY_RE.fullmatch(key) or _SENSITIVE_RE.search(key):
                    continue
                # Long benchmark request segments belong to generation context,
                # not to the semantic retrieval query sent to the embedder.
                if key.startswith("solicitud_"):
                    continue
                if not isinstance(value, str):
                    continue
                clean = " ".join(value.split())[:500]
                if clean and not _SENSITIVE_RE.search(clean):
                    values.append(f"{key}: {clean}")
        text = " ".join(values)
        if not text:
            raise ValueError("RAG_QUERY_EMPTY")
        if organization is not None:
            organization = " ".join(organization.split())[:200]
            if not organization or _SENSITIVE_RE.search(organization):
                raise ValueError("RAG_ORGANIZATION_INVALID")
        language = language.strip().lower()
        if not 2 <= len(language) <= 16 or _SENSITIVE_RE.search(language):
            raise ValueError("RAG_LANGUAGE_INVALID")
        return RagQuery(
            text=text,
            query_hash=sha256_text(text),
            filters={
                "document_type": "decreto",
                "document_subtype": self._document_subtype,
                "jurisdiction": "nacion",
                "review_status": "REVIEWED",
                "evaluation_split": "INDEX_90",
                "language": language,
                **({"organization": organization} if organization else {}),
            },
        )
