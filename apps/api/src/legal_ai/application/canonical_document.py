"""Build and canonically serialize the immutable final document snapshot."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from legal_ai.config import settings
from legal_ai.domain.canonical_document import CanonicalDocument
from legal_ai.domain.draft import Draft
from legal_ai.domain.errors import ContentTooLarge004Error, InvalidFinalizationError
from legal_ai.domain.review import DocumentReview


@dataclass(frozen=True)
class SerializedCanonicalDocument:
    """Snapshot plus its deterministic UTF-8 representation and digest."""

    snapshot: dict[str, Any]
    serialized: bytes
    sha256: str


class CanonicalDocumentBuilder:
    """Create the renderer-independent final snapshot from the review snapshot."""

    @staticmethod
    def build(draft: Draft, review: DocumentReview) -> CanonicalDocument:
        source = review.review_snapshot
        source_text = source.get("content")
        if not isinstance(source_text, str):
            source_text = source.get("source_text")
        if not isinstance(source_text, str) or not source_text:
            raise InvalidFinalizationError(details={"field": "review_snapshot.content"})

        title = source.get("title") or draft.title
        if not isinstance(title, str) or not title.strip():
            raise InvalidFinalizationError(details={"field": "document.title"})

        context = draft.context_snapshot
        locale = source.get("locale") or context.get("locale") or "es-AR"
        if not isinstance(locale, str) or not locale.strip():
            raise InvalidFinalizationError(details={"field": "document.locale"})

        supplied_document = source.get("document")
        document = (
            dict(supplied_document) if isinstance(supplied_document, dict) else {}
        )
        document.setdefault("title", title.strip())
        document.setdefault(
            "institutional_header", context.get("institutional_header", "")
        )
        document.setdefault("visto", [])
        document.setdefault("considerando", [])
        document.setdefault("por_ello", "")
        document.setdefault("articles", [])
        document.setdefault("signatures", [])
        document.setdefault("locale", locale.strip())

        source_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        return CanonicalDocument(
            schema_version=1,
            draft_id=str(draft.id),
            source_draft_version=review.draft_version,
            finalized_version=review.draft_version + 1,
            source_content_sha256=source_hash,
            document=document,
            source_text=source_text,
        )

    @staticmethod
    def build_preview(draft: Draft) -> CanonicalDocument:
        """Build a renderer-only view of the current approved draft."""
        source_text = draft.content or ""
        if not source_text:
            raise InvalidFinalizationError(details={"field": "draft.content"})
        context = draft.context_snapshot
        document = {
            "title": draft.title,
            "institutional_header": context.get("institutional_header", ""),
            "visto": [],
            "considerando": [],
            "por_ello": "",
            "articles": [],
            "signatures": [],
            "locale": context.get("locale", "es-AR"),
        }
        return CanonicalDocument(
            schema_version=1,
            draft_id=str(draft.id),
            source_draft_version=draft.version,
            finalized_version=draft.version,
            source_content_sha256=hashlib.sha256(
                source_text.encode("utf-8")
            ).hexdigest(),
            document=document,
            source_text=source_text,
        )

    @staticmethod
    def serialize(document: CanonicalDocument) -> SerializedCanonicalDocument:
        snapshot = document.as_snapshot()
        serialized = json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(serialized) > settings.export.max_final_snapshot_bytes:
            raise ContentTooLarge004Error(
                len(serialized), settings.export.max_final_snapshot_bytes
            )
        return SerializedCanonicalDocument(
            snapshot=snapshot,
            serialized=serialized,
            sha256=hashlib.sha256(serialized).hexdigest(),
        )
