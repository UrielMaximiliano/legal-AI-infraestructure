"""Initial export, metadata and download endpoints for increment 004."""

from __future__ import annotations

from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    Query,
    Request,
    Response,
)
from fastapi.responses import StreamingResponse

from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.adapters.storage.local_artifact_storage import LocalArtifactStorage
from legal_ai.api.dependencies import request_id_from, required_idempotency_key
from legal_ai.application.export_service import ExportService
from legal_ai.domain.errors import RangeNotSupportedError
from legal_ai.schemas.errors import ErrorResponse
from legal_ai.schemas.export import (
    CreateExportRequest,
    ExportAttemptResponse,
    ExportResponse,
    RegenerateExportRequest,
    RetryExportRequest,
)
from legal_ai.schemas.pagination import PaginatedResponse

router = APIRouter(tags=["exports"])


def _export_response(value: object, request_id: str) -> ExportResponse:
    model = ExportResponse.model_validate(value)
    if model.error_message:
        model = model.model_copy(
            update={"error_message": "La generación del artefacto falló"}
        )
    return model.model_copy(update={"request_id": request_id})


def _attempt_response(value: object, request_id: str) -> ExportAttemptResponse:
    model = ExportAttemptResponse.model_validate(value)
    if model.error_message:
        model = model.model_copy(
            update={"error_message": "La generación del artefacto falló"}
        )
    return model.model_copy(update={"request_id": request_id})


@router.post(
    "/api/v1/drafts/{draft_id}/exports",
    response_model=ExportResponse,
    status_code=202,
    responses={
        200: {"model": ExportResponse},
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def create_export(
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    draft_id: UUID,
    body: CreateExportRequest,
    idempotency_key: str = Depends(required_idempotency_key),
) -> ExportResponse:
    async with UnitOfWork() as uow:
        result = await ExportService(uow).create_initial(
            draft_id,
            body.draft_version,
            body.format,
            body.exported_by,
            idempotency_key,
            request_id_from(request),
        )
    if result.processing is not None:
        background_tasks.add_task(ExportService.process_operation, result.processing)
    response.status_code = result.status_code
    return _export_response(result.export, request_id_from(request))


@router.post(
    "/api/v1/exports/{export_id}/retry",
    response_model=ExportResponse,
    status_code=202,
    responses={200: {"model": ExportResponse}, 404: {"model": ErrorResponse}},
)
async def retry_export(
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    export_id: UUID,
    body: RetryExportRequest,
    idempotency_key: str = Depends(required_idempotency_key),
) -> ExportResponse:
    async with UnitOfWork() as uow:
        result = await ExportService(uow).retry_failed(
            export_id,
            body.exported_by,
            idempotency_key,
            request_id_from(request),
        )
    if result.processing is not None:
        background_tasks.add_task(ExportService.process_operation, result.processing)
    response.status_code = result.status_code
    return _export_response(result.export, request_id_from(request))


@router.post(
    "/api/v1/exports/{export_id}/regenerate",
    response_model=ExportResponse,
    status_code=202,
    responses={200: {"model": ExportResponse}, 404: {"model": ErrorResponse}},
)
async def regenerate_export(
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    export_id: UUID,
    body: RegenerateExportRequest,
    idempotency_key: str = Depends(required_idempotency_key),
) -> ExportResponse:
    async with UnitOfWork() as uow:
        result = await ExportService(uow).regenerate(
            export_id,
            body.expected_version,
            body.exported_by,
            idempotency_key,
            request_id_from(request),
        )
    if result.processing is not None:
        background_tasks.add_task(ExportService.process_operation, result.processing)
    response.status_code = result.status_code
    return _export_response(result.export, request_id_from(request))


@router.get(
    "/api/v1/drafts/{draft_id}/exports",
    response_model=PaginatedResponse[ExportResponse],
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def list_exports(
    request: Request,
    draft_id: UUID,
    draft_version: int | None = Query(None, gt=0),
    export_version: int | None = Query(None, gt=0),
    raw_format: str | None = Query(None, alias="format"),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    order: str = Query("created_at_desc"),
) -> PaginatedResponse[ExportResponse]:
    if order != "created_at_desc":
        from legal_ai.domain.errors import ValidationDomainError

        raise ValidationDomainError(details={"field": "order"})
    async with UnitOfWork() as uow:
        items, total = await ExportService(uow).list_exports(
            draft_id,
            page=page,
            page_size=page_size,
            raw_format=raw_format,
            status=status,
            draft_version=draft_version,
            export_version=export_version,
        )
    request_id = request_id_from(request)
    return PaginatedResponse(
        page=page,
        page_size=page_size,
        total=total,
        request_id=request_id,
        items=[_export_response(item, request_id) for item in items],
    )


@router.get(
    "/api/v1/exports/{export_id}",
    response_model=ExportResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_export(request: Request, export_id: UUID) -> ExportResponse:
    async with UnitOfWork() as uow:
        value = await ExportService(uow).get_export(export_id)
    return _export_response(value, request_id_from(request))


@router.get(
    "/api/v1/exports/{export_id}/attempts",
    response_model=PaginatedResponse[ExportAttemptResponse],
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def list_export_attempts(
    request: Request,
    export_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    order: str = Query("created_at_desc"),
) -> PaginatedResponse[ExportAttemptResponse]:
    if order != "created_at_desc":
        from legal_ai.domain.errors import ValidationDomainError

        raise ValidationDomainError(details={"field": "order"})
    async with UnitOfWork() as uow:
        items, total = await ExportService(uow).list_attempts(
            export_id, page=page, page_size=page_size
        )
    request_id = request_id_from(request)
    return PaginatedResponse(
        page=page,
        page_size=page_size,
        total=total,
        request_id=request_id,
        items=[_attempt_response(item, request_id) for item in items],
    )


@router.get(
    "/api/v1/exports/{export_id}/download",
    responses={
        200: {"content": {"application/octet-stream": {}}},
        304: {"description": "Not modified"},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        410: {"model": ErrorResponse},
        416: {"model": ErrorResponse},
    },
)
async def download_export(
    request: Request,
    export_id: UUID,
    range_header: str | None = Header(default=None, alias="Range"),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
) -> Response:
    if range_header is not None:
        raise RangeNotSupportedError()
    async with UnitOfWork() as uow:
        result = await ExportService(uow).prepare_download(
            export_id, request_id_from(request)
        )
    headers = {
        "ETag": result.etag,
        "Cache-Control": "private, no-store",
        "Accept-Ranges": "none",
        "X-Request-ID": request_id_from(request),
    }
    if if_none_match == result.etag:
        return Response(status_code=304, headers=headers)
    headers.update(
        {
            "Content-Disposition": f'attachment; filename="{result.export.file_name}"',
            "Content-Length": str(result.content_length),
        }
    )
    storage = LocalArtifactStorage()
    return StreamingResponse(
        storage.stream(result.relative_path),
        media_type=result.content_type,
        headers=headers,
    )
