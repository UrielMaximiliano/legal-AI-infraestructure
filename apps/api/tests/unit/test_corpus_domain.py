import uuid
from datetime import UTC, datetime

import pytest

from legal_ai.domain.corpus import (
    CorpusChunk,
    CorpusDocument,
    CorpusDomainError,
    CorpusIngestionStatus,
    InvalidReviewTransitionError,
    ProvenanceType,
    ReviewStatus,
    ReviewVersionMismatchError,
    sha256_text,
)


def make_document() -> CorpusDocument:
    raw = "texto original"
    normalized = "Texto original"
    return CorpusDocument(
        id=uuid.uuid4(),
        source_identifier="fixture/legal.txt",
        raw_content=raw,
        normalized_content=normalized,
        raw_content_hash=sha256_text(raw),
        normalized_content_hash=sha256_text(normalized),
    )


def test_raw_content_is_protected_and_review_increments_once() -> None:
    document = make_document()
    assert "texto original" not in repr(document)
    document.transition_review(
        ReviewStatus.REVIEWED,
        expected_version=1,
        reviewed_by="reviewer",
        reviewed_at=datetime.now(UTC),
    )
    assert document.review_version == 2
    assert document.review_status is ReviewStatus.REVIEWED
    with pytest.raises(InvalidReviewTransitionError):
        document.transition_review(
            ReviewStatus.REJECTED,
            expected_version=2,
            reviewed_by="reviewer-2",
            reviewed_at=datetime.now(UTC),
            review_notes="no corresponde",
        )


def test_ingestion_statuses_follow_contractual_pipeline() -> None:
    document = make_document()
    for status in (
        CorpusIngestionStatus.PARSED,
        CorpusIngestionStatus.NORMALIZED,
        CorpusIngestionStatus.VALIDATED,
        CorpusIngestionStatus.CHUNKED,
        CorpusIngestionStatus.EMBEDDING,
        CorpusIngestionStatus.INDEXED,
        CorpusIngestionStatus.COMPLETED,
    ):
        document.transition_ingestion(status)
    with pytest.raises(ValueError):
        document.transition_ingestion(CorpusIngestionStatus.FAILED)


def test_review_cas_and_transition_errors_are_distinct() -> None:
    document = make_document()
    with pytest.raises(ReviewVersionMismatchError):
        document.transition_review(
            ReviewStatus.REVIEWED,
            expected_version=2,
            reviewed_by="reviewer",
            reviewed_at=datetime.now(UTC),
        )
    with pytest.raises(InvalidReviewTransitionError):
        document.transition_review(
            ReviewStatus.REJECTED,
            expected_version=1,
            reviewed_by="reviewer",
            reviewed_at=datetime.now(UTC),
        )
    document.transition_review(
        ReviewStatus.REJECTED,
        expected_version=1,
        reviewed_by="reviewer",
        reviewed_at=datetime.now(UTC),
        review_notes="documento fuera del subtipo contractual",
    )
    with pytest.raises(InvalidReviewTransitionError):
        document.transition_review(
            ReviewStatus.REVIEWED,
            expected_version=2,
            reviewed_by="reviewer",
            reviewed_at=datetime.now(UTC),
        )


def test_document_invariants_protect_content_provenance_and_hashes() -> None:
    with pytest.raises(ValueError, match="CORPUS_RAW_CONTENT_EMPTY"):
        CorpusDocument(
            id=uuid.uuid4(),
            source_identifier="fixture/empty.txt",
            raw_content="",
            normalized_content="normalized",
            raw_content_hash=sha256_text(""),
            normalized_content_hash=sha256_text("normalized"),
        )
    with pytest.raises(ValueError, match="CORPUS_RAW_CONTENT_EMPTY"):
        CorpusDocument(
            id=uuid.uuid4(),
            source_identifier="fixture/blank.txt",
            raw_content="   ",
            normalized_content="normalized",
            raw_content_hash=sha256_text("   "),
            normalized_content_hash=sha256_text("normalized"),
        )

    document = CorpusDocument(
        id=uuid.uuid4(),
        source_identifier="fixture/pipeline.txt",
        raw_content="raw",
        normalized_content="",
        raw_content_hash=sha256_text("raw"),
        normalized_content_hash=sha256_text(""),
    )
    with pytest.raises(ValueError, match="CORPUS_NORMALIZED_CONTENT_EMPTY"):
        document.transition_ingestion(CorpusIngestionStatus.PARSED)

    with pytest.raises(ValueError, match="CORPUS_REVIEW_PROVENANCE_INVALID"):
        CorpusDocument(
            id=uuid.uuid4(),
            source_identifier="fixture/automated-reviewed.txt",
            raw_content="raw",
            normalized_content="normalized",
            raw_content_hash=sha256_text("raw"),
            normalized_content_hash=sha256_text("normalized"),
            review_status=ReviewStatus.REVIEWED,
            provenance_type=ProvenanceType.AUTOMATED,
            reviewed_by="reviewer",
            reviewed_at=datetime.now(UTC),
        )

    with pytest.raises(ValueError, match="CORPUS_CONTENT_HASH_INVALID"):
        CorpusDocument(
            id=uuid.uuid4(),
            source_identifier="fixture/uppercase-hash.txt",
            raw_content="raw",
            normalized_content="normalized",
            raw_content_hash="A" * 64,
            normalized_content_hash=sha256_text("normalized"),
        )


def test_chunk_invariants_protect_content_state_and_embedding_metadata() -> None:
    common = {
        "id": uuid.uuid4(),
        "document_id": uuid.uuid4(),
        "content_hash": sha256_text("content"),
        "generation": 1,
        "section_index": 0,
        "paragraph_index": 0,
    }
    with pytest.raises(CorpusDomainError, match="CONTENT_EMPTY"):
        CorpusChunk(content="   ", **common)
    with pytest.raises(CorpusDomainError, match="STATE_INVALID"):
        CorpusChunk(content="content", state="UNKNOWN", **common)
    with pytest.raises(CorpusDomainError, match="EMBEDDING_REQUIRED"):
        CorpusChunk(content="content", state="ACTIVE", **common)
    with pytest.raises(CorpusDomainError, match="EMBEDDING_METADATA_INVALID"):
        CorpusChunk(content="content", embedding=tuple([0.0] * 1024), **common)
    with pytest.raises(CorpusDomainError, match="INDEX_INVALID"):
        CorpusChunk(content="content", token_count=-1, **common)
