"""Application service for optimistic, auditable corpus review."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from legal_ai.domain.corpus import ReviewStatus
from legal_ai.domain.review_event import ReviewEvent
from legal_ai.schemas.corpus_review import CorpusReviewRequest, CorpusReviewResult


class CorpusReviewService:
    """Keep review decisions behind the repository CAS and one UoW."""

    def __init__(self, uow: Any) -> None:
        self._uow = uow

    async def review(
        self,
        request: CorpusReviewRequest,
        *,
        request_id: str | None = None,
    ) -> CorpusReviewResult:
        target = ReviewStatus.REVIEWED if request.approve else ReviewStatus.REJECTED
        document = await self._uow.corpus_documents.compare_and_swap_review(
            request.document_id,
            expected_version=request.expected_version,
            expected_status=ReviewStatus.PENDING_REVIEW,
            new_status=target,
            reviewed_by=request.reviewed_by,
            reason=request.reason,
        )
        if hasattr(self._uow, "review_events"):
            await self._uow.review_events.create(
                ReviewEvent(
                    id=uuid.uuid4(),
                    resource_type="CORPUS_DOCUMENT",
                    resource_id=str(request.document_id),
                    event_type=(
                        "CORPUS_DOCUMENT_APPROVED"
                        if request.approve
                        else "CORPUS_DOCUMENT_REJECTED"
                    ),
                    actor=document.reviewed_by,
                    request_id=request_id,
                    summary={
                        "from_status": ReviewStatus.PENDING_REVIEW.value,
                        "to_status": document.review_status.value,
                        "expected_version": request.expected_version,
                        "review_version": document.review_version,
                    },
                    created_at=datetime.now(UTC),
                )
            )
        if document.reviewed_by is None or document.reviewed_at is None:
            raise ValueError("CORPUS_REVIEW_RESULT_INVALID")
        return CorpusReviewResult(
            document_id=document.id,
            status=document.review_status.value,
            review_version=document.review_version,
            reviewed_by=document.reviewed_by,
            reviewed_at=document.reviewed_at,
            request_id=request_id,
        )
