"""Human-review API endpoints for increment 004."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.api.dependencies import request_id_from, required_idempotency_key
from legal_ai.application.review_service import ReviewService
from legal_ai.domain.enums import CommentStatus
from legal_ai.domain.review_comment import ReviewComment
from legal_ai.schemas.errors import ErrorResponse
from legal_ai.schemas.pagination import PaginatedResponse
from legal_ai.schemas.review import (
    ReviewApproveRequest,
    ReviewCommentCreateRequest,
    ReviewCommentResponse,
    ReviewCommentUpdateRequest,
    ReviewCreateRequest,
    ReviewEventResponse,
    ReviewRequestChangesRequest,
    ReviewResponse,
    ReviewSubmitRequest,
)

router = APIRouter(tags=["reviews"])


def _review_response(value: Any) -> ReviewResponse:
    return ReviewResponse.model_validate(value)


def _comment_response(value: Any) -> ReviewCommentResponse:
    return ReviewCommentResponse.model_validate(value)


@router.get(
    "/api/v1/drafts/{draft_id}/reviews/current",
    response_model=ReviewResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_current_review(request: Request, draft_id: UUID) -> ReviewResponse:
    async with UnitOfWork() as uow:
        review = await ReviewService(uow).current(draft_id)
    return _review_response(review)


@router.post(
    "/api/v1/drafts/{draft_id}/reviews",
    response_model=ReviewResponse,
    status_code=201,
    responses={
        200: {"model": ReviewResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def create_review(
    request: Request,
    response: Response,
    draft_id: UUID,
    body: ReviewCreateRequest,
    idempotency_key: str = Depends(required_idempotency_key),
) -> ReviewResponse:
    async with UnitOfWork() as uow:
        result = await ReviewService(uow).create_review(
            draft_id,
            body.draft_version,
            body.expected_version,
            body.opened_by,
            idempotency_key,
            request_id_from(request),
        )
    response.status_code = result.status_code
    return _review_response(result.value)


@router.post(
    "/api/v1/reviews/{review_id}/comments",
    response_model=ReviewCommentResponse,
    status_code=201,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def add_review_comment(
    request: Request,
    response: Response,
    review_id: UUID,
    body: ReviewCommentCreateRequest,
    idempotency_key: str = Depends(required_idempotency_key),
) -> ReviewCommentResponse:
    now = datetime.now(UTC)
    comment = ReviewComment(
        id=uuid.uuid4(),
        review_id=review_id,
        draft_version=body.draft_version,
        author=body.author,
        severity=body.severity,
        status=CommentStatus.OPEN,
        body=body.body.strip(),
        version=1,
        created_at=now,
        updated_at=now,
        parent_comment_id=body.parent_comment_id,
        anchor=body.anchor,
    )
    async with UnitOfWork() as uow:
        result = await ReviewService(uow).add_comment(
            review_id,
            comment,
            idempotency_key,
            request_id_from(request),
            body.model_dump(mode="json"),
        )
    response.status_code = result.status_code
    return _comment_response(result.value)


@router.patch(
    "/api/v1/reviews/{review_id}/comments/{comment_id}",
    response_model=ReviewCommentResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def update_review_comment(
    request: Request,
    response: Response,
    review_id: UUID,
    comment_id: UUID,
    body: ReviewCommentUpdateRequest,
    idempotency_key: str = Depends(required_idempotency_key),
) -> ReviewCommentResponse:
    async with UnitOfWork() as uow:
        result = await ReviewService(uow).update_comment(
            review_id,
            comment_id,
            body.expected_version,
            body.status,
            body.resolved_by,
            idempotency_key,
            request_id_from(request),
            body.model_dump(mode="json"),
        )
    response.status_code = result.status_code
    return _comment_response(result.value)


@router.post(
    "/api/v1/reviews/{review_id}/submit",
    response_model=ReviewResponse,
    responses={409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def submit_review(
    request: Request,
    response: Response,
    review_id: UUID,
    body: ReviewSubmitRequest,
    idempotency_key: str = Depends(required_idempotency_key),
) -> ReviewResponse:
    async with UnitOfWork() as uow:
        result = await ReviewService(uow).submit(
            review_id,
            body.expected_version,
            body.submitted_by,
            idempotency_key,
            request_id_from(request),
            body.model_dump(mode="json"),
        )
    response.status_code = result.status_code
    return _review_response(result.value)


@router.post(
    "/api/v1/reviews/{review_id}/approve",
    response_model=ReviewResponse,
    responses={409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def approve_review(
    request: Request,
    response: Response,
    review_id: UUID,
    body: ReviewApproveRequest,
    idempotency_key: str = Depends(required_idempotency_key),
) -> ReviewResponse:
    async with UnitOfWork() as uow:
        result = await ReviewService(uow).approve(
            review_id,
            body.expected_version,
            body.decided_by,
            body.human_review_confirmed,
            idempotency_key,
            request_id_from(request),
            body.model_dump(mode="json"),
        )
    response.status_code = result.status_code
    return _review_response(result.value)


@router.post(
    "/api/v1/reviews/{review_id}/request-changes",
    response_model=ReviewResponse,
    responses={409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def request_review_changes(
    request: Request,
    response: Response,
    review_id: UUID,
    body: ReviewRequestChangesRequest,
    idempotency_key: str = Depends(required_idempotency_key),
) -> ReviewResponse:
    async with UnitOfWork() as uow:
        result = await ReviewService(uow).request_changes(
            review_id,
            body.expected_version,
            body.decided_by,
            body.reason,
            idempotency_key,
            request_id_from(request),
            body.model_dump(mode="json"),
        )
    response.status_code = result.status_code
    return _review_response(result.value)


@router.get(
    "/api/v1/reviews/{review_id}/history",
    response_model=PaginatedResponse[ReviewEventResponse],
    responses={404: {"model": ErrorResponse}},
)
async def review_history(
    request: Request,
    review_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    order: str = Query("created_at_desc"),
) -> PaginatedResponse[ReviewEventResponse]:
    if order != "created_at_desc":
        from legal_ai.domain.errors import ValidationDomainError

        raise ValidationDomainError(details={"field": "order"})
    async with UnitOfWork() as uow:
        events, total = await ReviewService(uow).history(
            review_id, (page - 1) * page_size, page_size
        )
    return PaginatedResponse(
        page=page,
        page_size=page_size,
        total=total,
        request_id=request_id_from(request),
        items=[ReviewEventResponse.model_validate(event) for event in events],
    )
