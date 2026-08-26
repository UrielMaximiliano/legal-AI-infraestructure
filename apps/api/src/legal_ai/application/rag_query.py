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

    def build(
        self,
        *,
        case_file: dict[str, str] | None = None,
        template: dict[str, str] | None = None,
        variables: dict[str, str] | None = None,
        document_type: str | None = None,
        document_subtype: str | None = None,
        jurisdiction: str | None = None,
        organization: str | None = None,
        language: str = "es",
    ) -> RagQuery:
        values: list[str] = []
        for group in (case_file or {}, template or {}, variables or {}):
            for key, value in sorted(group.items()):
                if not _KEY_RE.fullmatch(key) or _SENSITIVE_RE.search(key):
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
        policy_filters: dict[str, str | None] = {
            "document_type": document_type,
            "document_subtype": document_subtype,
            "jurisdiction": jurisdiction,
        }
        for filter_key, filter_value in policy_filters.items():
            if filter_value is None:
                continue
            if not isinstance(filter_value, str):
                raise ValueError("RAG_FILTER_INVALID")
            clean = " ".join(filter_value.split())[:120]
            if not clean or _SENSITIVE_RE.search(clean):
                raise ValueError("RAG_FILTER_INVALID")
            policy_filters[filter_key] = clean
        return RagQuery(
            text=text,
            query_hash=sha256_text(text),
            filters={
                **{
                    key: value
                    for key, value in policy_filters.items()
                    if value is not None
                },
                "review_status": "REVIEWED",
                "evaluation_split": "INDEX_90",
                "language": language,
                **({"organization": organization} if organization else {}),
            },
        )
