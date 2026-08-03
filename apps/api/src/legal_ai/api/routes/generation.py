"""Generation attempt endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request

from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.schemas.errors import ErrorResponse
from legal_ai.schemas.generation import GenerationAttemptResponse

router = APIRouter(tags=["generation"])


class GenerationAttemptNotFoundError(Exception):
    """Generation attempt not found."""

    def __init__(self, attempt_id: str) -> None:
        self.attempt_id = attempt_id
        super().__init__(f"Generation attempt not found: {attempt_id}")


@router.get(
    "/api/v1/generation-attempts/{attempt_id}",
    response_model=GenerationAttemptResponse,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def get_generation_attempt(
    request: Request,
    attempt_id: UUID,
) -> GenerationAttemptResponse:
    async with UnitOfWork() as uow:
        attempt = await uow.generation_attempts.get_by_id(attempt_id)
        if not attempt:
            raise GenerationAttemptNotFoundError(str(attempt_id))
    return GenerationAttemptResponse.model_validate(attempt)


@router.get(
    "/api/v1/case-files/{case_file_id}/generation-attempts",
    response_model=list[GenerationAttemptResponse],
    responses={
        404: {"model": ErrorResponse},
    },
)
async def list_generation_attempts(
    request: Request,
    case_file_id: UUID,
) -> list[GenerationAttemptResponse]:
    async with UnitOfWork() as uow:
        attempts = await uow.generation_attempts.list_by_case_file(case_file_id)
    return [GenerationAttemptResponse.model_validate(a) for a in attempts]
