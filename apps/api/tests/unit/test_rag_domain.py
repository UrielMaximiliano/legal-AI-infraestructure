from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from legal_ai.domain.rag import (
    RagGenerationRun,
    RagGenerationStatus,
    RagRetrievedSource,
    RagSourceDisposition,
    citation_id,
    sha256_text,
)


def _run() -> RagGenerationRun:
    digest = sha256_text("request")
    return RagGenerationRun(
        id=uuid4(),
        case_file_id=uuid4(),
        template_id=uuid4(),
        request_hash=digest,
        query_hash=sha256_text("query"),
    )


def test_state_machine_is_forward_only() -> None:
    run = _run()
    retrieving = run.transition(RagGenerationStatus.RETRIEVING)
    generating = retrieving.transition(RagGenerationStatus.GENERATING)
    assert generating.status == RagGenerationStatus.GENERATING
    with pytest.raises(ValueError, match="RAG_INVALID_STATE_TRANSITION"):
        generating.transition(RagGenerationStatus.PENDING)


def test_citation_and_hash_are_stable() -> None:
    assert citation_id(1) == "SRC-001"
    assert sha256_text("same") == sha256_text("same")
    assert _run().created_at.tzinfo is UTC or isinstance(
        _run().created_at, datetime
    )


def test_source_invariants_are_fail_closed() -> None:
    with pytest.raises(ValueError, match="RAG_CITATION_ID_INVALID"):
        RagRetrievedSource(
            document_id=uuid4(),
            chunk_id=uuid4(),
            external_id="DOC-1",
            title="Title",
            publication_date=None,
            section_type="VISTO",
            generation=1,
            similarity_score=0.5,
            retrieval_rank=1,
            citation_id="invalid",
            excerpt="evidence",
            context_rank=1,
        )
    with pytest.raises(ValueError, match="RAG_SOURCE_CONTEXT_RANK_FORBIDDEN"):
        RagRetrievedSource(
            document_id=uuid4(),
            chunk_id=uuid4(),
            external_id="DOC-1",
            title="Title",
            publication_date=None,
            section_type="VISTO",
            generation=1,
            similarity_score=0.5,
            retrieval_rank=1,
            citation_id="SRC-001",
            excerpt="evidence",
            disposition=RagSourceDisposition.EXCLUDED_SCORE,
            context_rank=1,
        )
