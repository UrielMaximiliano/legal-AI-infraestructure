"""Unit tests for canonical final snapshots."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

import pytest

from legal_ai.application.canonical_document import CanonicalDocumentBuilder
from legal_ai.config import settings
from legal_ai.domain.draft import Draft
from legal_ai.domain.enums import DraftStatus, ReviewStatus
from legal_ai.domain.errors import ContentTooLarge004Error
from legal_ai.domain.review import DocumentReview


def _entities(content: str = "Contenido aprobado") -> tuple[Draft, DocumentReview]:
    now = datetime.now(UTC)
    draft = Draft(
        id=uuid.uuid4(),
        template_id=uuid.uuid4(),
        case_file_id=uuid.uuid4(),
        title="Resolución",
        content=content,
        status=DraftStatus.APROBADO,
        version=4,
        generation_number=1,
        context_snapshot={"locale": "es-AR"},
        context_hash="a" * 64,
        created_at=now,
        updated_at=now,
    )
    snapshot = {
        "draft_id": str(draft.id),
        "draft_version": 4,
        "title": draft.title,
        "content": content,
    }
    review = DocumentReview(
        id=uuid.uuid4(),
        draft_id=draft.id,
        draft_version=4,
        review_snapshot=snapshot,
        review_snapshot_sha256="b" * 64,
        status=ReviewStatus.CLOSED,
        opened_by="Reviewer",
        version=2,
        opened_at=now,
        created_at=now,
        updated_at=now,
        closed_at=now,
        decided_at=now,
    )
    return draft, review


@pytest.mark.unit
def test_canonical_snapshot_is_deterministic_and_excludes_case_identity() -> None:
    draft, review = _entities("Texto con acentos: acción")
    first = CanonicalDocumentBuilder.serialize(
        CanonicalDocumentBuilder.build(draft, review)
    )
    second = CanonicalDocumentBuilder.serialize(
        CanonicalDocumentBuilder.build(draft, review)
    )
    assert first.serialized == second.serialized
    assert first.sha256 == hashlib.sha256(first.serialized).hexdigest()
    assert str(draft.case_file_id) not in first.serialized.decode()
    assert json.loads(first.serialized)["finalized_version"] == 5


@pytest.mark.unit
def test_canonical_snapshot_accepts_exact_byte_limit_and_rejects_one_more(
    monkeypatch,
) -> None:
    draft, review = _entities("x" * 500)
    document = CanonicalDocumentBuilder.build(draft, review)
    serialized = CanonicalDocumentBuilder.serialize(document)
    monkeypatch.setattr(
        settings.export, "max_final_snapshot_bytes", len(serialized.serialized)
    )
    assert (
        CanonicalDocumentBuilder.serialize(document).serialized == serialized.serialized
    )
    larger = document.__class__(
        **{**document.__dict__, "source_text": document.source_text + "y"}
    )
    with pytest.raises(ContentTooLarge004Error):
        CanonicalDocumentBuilder.serialize(larger)
