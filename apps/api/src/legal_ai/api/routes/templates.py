"""Template endpoints."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from fastapi import (
    APIRouter,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)

from legal_ai.adapters.database.imi_core import ImiCoreUnitOfWork
from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.application.docx_parser import DOCX_MIME, DocxParser
from legal_ai.application.template_management import (
    TEMPLATE_EXTRACTOR_VERSION,
    extract_file_content,
    parser_candidates_to_safe,
    preview_document,
    suggestions_for_body,
    suggestions_to_candidates,
    validate_definition,
)
from legal_ai.application.template_service import TemplateService
from legal_ai.config import settings
from legal_ai.domain.errors import (
    IdempotencyKeyRequiredError,
    TemplateAnalysisNotFoundError,
    TemplateImportInvalidError,
    TemplateImportNotFoundError,
    ValidationDomainError,
)
from legal_ai.schemas.errors import ErrorResponse
from legal_ai.schemas.pagination import PaginatedResponse
from legal_ai.schemas.template import (
    CreateTemplateRequest,
    PublishTemplateRequest,
    SaveImportDecisionsRequest,
    TemplateAnalysisRequest,
    TemplateAnalysisResponse,
    TemplateImportResponse,
    TemplatePreviewRequest,
    TemplatePreviewResponse,
    TemplateResponse,
    TemplateVersionRequest,
    TemplateVersionResponse,
    UpdateTemplateRequest,
    ValidateTemplateRequest,
    ValidateTemplateResponse,
)
from legal_ai.schemas.validation import validate_idempotency_key

router = APIRouter(prefix="/api/v1/templates", tags=["templates"])
template_jobs_router = APIRouter(tags=["template-management"])


def _request_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode(
            "utf-8"
        )
    ).hexdigest()


def _imi_idempotency_key(value: str | None) -> str | None:
    if settings.rag_profile.code != "imi_leg_06b":
        return value
    if value is None:
        raise IdempotencyKeyRequiredError()
    try:
        return validate_idempotency_key(value)
    except ValueError as exc:
        raise ValidationDomainError(
            "Idempotency-Key tiene un formato invÃ¡lido",
            details={"field": "Idempotency-Key"},
        ) from exc


def _actor(request: Request) -> str:
    return request.headers.get("x-actor") or "imi-leg"


def _extraction_provenance(
    filename: str,
    content_type: str | None,
    data: bytes,
    body: str,
) -> tuple[str, int, str, list[dict[str, Any]]]:
    """Build controlled source metadata without logging content or PII."""
    source_sha256 = hashlib.sha256(data).hexdigest()
    source_size = len(data)
    extractor_version = TEMPLATE_EXTRACTOR_VERSION
    candidates: list[dict[str, Any]] = []
    lowered = filename.lower()
    is_docx = lowered.endswith(".docx") or (
        "wordprocessingml.document" in (content_type or "")
    )
    if is_docx:
        try:
            declared = content_type if content_type == DOCX_MIME else None
            parsed = DocxParser().parse_bytes(
                data, filename=filename, declared_mime=declared
            )
            candidates = parser_candidates_to_safe(parsed.candidates)
        except Exception:
            candidates = []
    else:
        try:
            candidates = suggestions_to_candidates(suggestions_for_body(body, []))
        except Exception:
            candidates = []
    return source_sha256, source_size, extractor_version, candidates


def _reject_legacy_write() -> None:
    """Prevent IMI requests from silently writing to the legacy database."""
    if settings.rag_profile.code == "imi_leg_06b":
        raise HTTPException(
            status_code=501,
            detail={
                "code": "IMI_CORE_WRITE_NOT_IMPLEMENTED",
                "message": (
                    "Las escrituras de plantillas de IMI requieren el repositorio "
                    "imi_leg_core."
                ),
            },
        )


@router.post(
    "",
    response_model=TemplateResponse,
    status_code=201,
    responses={
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def create_template(
    request: Request,
    response: Response,
    body: CreateTemplateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> TemplateResponse:
    if settings.rag_profile.code == "imi_leg_06b":
        key = _imi_idempotency_key(idempotency_key)
        payload = body.model_dump(mode="json")
        async with ImiCoreUnitOfWork() as uow:
            if uow.core is None:
                raise RuntimeError("IMI_CORE_UNAVAILABLE")
            template, created = await uow.core.create_template(
                name=body.name,
                document_type=body.document_type,
                body=body.body_template,
                fields=body.fields,
                rules=body.rules,
                blocks=body.blocks,
                instructions=body.instructions,
                organ_emisor=body.organ_emisor,
                normativa=body.normativa,
                description=body.description,
                actor=_actor(request),
                idempotency_key=key,
                request_hash=_request_hash(payload),
            )
        response.status_code = 201 if created else 200
        return TemplateResponse.model_validate(template)
    async with UnitOfWork() as uow:
        service = TemplateService(uow)
        from legal_ai.domain.enums import TemplateDocumentType

        template = await service.create_template(
            name=body.name,
            document_type=TemplateDocumentType(body.document_type),
            body_template=body.body_template,
            organ_emisor=body.organ_emisor,
            normativa=body.normativa,
            description=body.description,
            variables=body.variables,
        )
    return TemplateResponse.model_validate(template)


@router.get(
    "",
    response_model=PaginatedResponse[TemplateResponse],
    responses={422: {"model": ErrorResponse}},
)
async def list_templates(
    request: Request,
    document_type: str | None = Query(None),
    search: str | None = Query(None),
    status: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> PaginatedResponse[TemplateResponse]:
    if settings.rag_profile.code == "imi_leg_06b":
        async with ImiCoreUnitOfWork() as uow:
            if uow.core is None:
                raise RuntimeError("IMI_CORE_UNAVAILABLE")
            items, total = await uow.core.list_templates(
                document_type=document_type,
                search=search,
                skip=skip,
                limit=limit,
                status=status,
            )
        return PaginatedResponse(
            page=skip // limit + 1,
            page_size=limit,
            total=total,
            items=[TemplateResponse.model_validate(t) for t in items],
        )
    async with UnitOfWork() as uow:
        service = TemplateService(uow)
        items, total = await service.list_templates(document_type, search, skip, limit)
    return PaginatedResponse(
        page=skip // limit + 1,
        page_size=limit,
        total=total,
        items=[TemplateResponse.model_validate(t) for t in items],
    )


@router.get(
    "/{template_id}/versions",
    response_model=PaginatedResponse[TemplateVersionResponse],
    responses={404: {"model": ErrorResponse}},
)
async def list_template_versions(
    request: Request,
    template_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=100),
) -> PaginatedResponse[TemplateVersionResponse]:
    if settings.rag_profile.code != "imi_leg_06b":
        raise HTTPException(
            status_code=501, detail="Versiones de plantillas no disponibles"
        )
    async with ImiCoreUnitOfWork() as uow:
        if uow.core is None:
            raise RuntimeError("IMI_CORE_UNAVAILABLE")
        template = await uow.core.get_template(template_id)
        if template is None:
            from legal_ai.application.template_service import TemplateNotFoundError

            raise TemplateNotFoundError(str(template_id))
        items, total = await uow.core.list_template_versions(
            template_id,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
    return PaginatedResponse(
        page=page,
        page_size=page_size,
        total=total,
        request_id=str(getattr(request.state, "request_id", "")),
        items=[TemplateVersionResponse.model_validate(item) for item in items],
    )


@router.post(
    "/{template_id}/versions",
    response_model=TemplateVersionResponse,
    status_code=201,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def create_template_version(
    request: Request,
    response: Response,
    template_id: UUID,
    body: TemplateVersionRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> TemplateVersionResponse:
    if settings.rag_profile.code != "imi_leg_06b":
        raise HTTPException(
            status_code=501, detail="Versiones de plantillas no disponibles"
        )
    key = _imi_idempotency_key(idempotency_key)
    payload = body.model_dump(mode="json")
    async with ImiCoreUnitOfWork() as uow:
        if uow.core is None:
            raise RuntimeError("IMI_CORE_UNAVAILABLE")
        version, created = await uow.core.create_template_version(
            template_id=template_id,
            body=body.body_template,
            fields=body.fields,
            rules=body.rules,
            blocks=body.blocks,
            instructions=body.instructions,
            idempotency_key=key,
            request_hash=_request_hash(payload),
        )
    response.status_code = 201 if created else 200
    return TemplateVersionResponse.model_validate(version)


@router.get(
    "/{template_id}/versions/{version_id}",
    response_model=TemplateVersionResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_template_version(
    template_id: UUID,
    version_id: UUID,
) -> TemplateVersionResponse:
    if settings.rag_profile.code != "imi_leg_06b":
        raise HTTPException(
            status_code=501, detail="Versiones de plantillas no disponibles"
        )
    async with ImiCoreUnitOfWork() as uow:
        if uow.core is None:
            raise RuntimeError("IMI_CORE_UNAVAILABLE")
        version = await uow.core.get_template_version(template_id, version_id)
    if version is None:
        from legal_ai.application.template_service import TemplateNotFoundError

        raise TemplateNotFoundError(str(template_id))
    return TemplateVersionResponse.model_validate(version)


@router.patch(
    "/{template_id}/versions/{version_id}",
    response_model=TemplateVersionResponse,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def update_template_version(
    request: Request,
    response: Response,
    template_id: UUID,
    version_id: UUID,
    body: UpdateTemplateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> TemplateVersionResponse:
    if settings.rag_profile.code != "imi_leg_06b":
        raise HTTPException(
            status_code=501, detail="Versiones de plantillas no disponibles"
        )
    key = _imi_idempotency_key(idempotency_key)
    payload = body.model_dump(exclude_unset=True, mode="json")
    async with ImiCoreUnitOfWork() as uow:
        if uow.core is None:
            raise RuntimeError("IMI_CORE_UNAVAILABLE")
        version, created = await uow.core.update_template_version(
            template_id=template_id,
            version_id=version_id,
            payload=payload,
            idempotency_key=key,
            request_hash=_request_hash(payload),
        )
    response.status_code = 200 if not created else 200
    return TemplateVersionResponse.model_validate(version)


@router.post(
    "/{template_id}/versions/{version_id}/publish",
    response_model=TemplateVersionResponse,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def publish_template_version(
    request: Request,
    response: Response,
    template_id: UUID,
    version_id: UUID,
    body: PublishTemplateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> TemplateVersionResponse:
    if settings.rag_profile.code != "imi_leg_06b":
        raise HTTPException(
            status_code=501, detail="Versiones de plantillas no disponibles"
        )
    key = _imi_idempotency_key(idempotency_key)
    payload = body.model_dump(mode="json")
    async with ImiCoreUnitOfWork() as uow:
        if uow.core is None:
            raise RuntimeError("IMI_CORE_UNAVAILABLE")
        version, created = await uow.core.publish_template_version(
            template_id=template_id,
            version_id=version_id,
            revision=body.revision,
            confirm_warnings=body.confirm_warnings,
            idempotency_key=key,
            request_hash=_request_hash(payload),
            actor=_actor(request),
        )
    response.status_code = 201 if created else 200
    return TemplateVersionResponse.model_validate(version)


@router.get(
    "/{template_id}",
    response_model=TemplateResponse,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def get_template(
    request: Request,
    template_id: UUID,
) -> TemplateResponse:
    if settings.rag_profile.code == "imi_leg_06b":
        async with ImiCoreUnitOfWork() as uow:
            if uow.core is None:
                raise RuntimeError("IMI_CORE_UNAVAILABLE")
            template = await uow.core.get_template(template_id)
        if template is None:
            from legal_ai.application.template_service import TemplateNotFoundError

            raise TemplateNotFoundError(str(template_id))
        return TemplateResponse.model_validate(template)
    async with UnitOfWork() as uow:
        service = TemplateService(uow)
        template = await service.get_template(str(template_id))
    return TemplateResponse.model_validate(template)


@router.patch(
    "/{template_id}",
    response_model=TemplateResponse,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def update_template(
    request: Request,
    template_id: UUID,
    body: UpdateTemplateRequest,
) -> TemplateResponse:
    _reject_legacy_write()
    async with UnitOfWork() as uow:
        service = TemplateService(uow)
        template = await service.update_template(
            str(template_id),
            body_template=body.body_template,
            organ_emisor=body.organ_emisor,
            normativa=body.normativa,
            description=body.description,
            variables=body.variables,
        )
    return TemplateResponse.model_validate(template)


@router.post(
    "/{template_id}/deactivate",
    response_model=TemplateResponse,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def deactivate_template(
    request: Request,
    response: Response,
    template_id: UUID,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> TemplateResponse:
    if settings.rag_profile.code == "imi_leg_06b":
        key = _imi_idempotency_key(idempotency_key)
        async with ImiCoreUnitOfWork() as uow:
            if uow.core is None:
                raise RuntimeError("IMI_CORE_UNAVAILABLE")
            template, _created = await uow.core.deactivate_template_core(
                template_id,
                idempotency_key=key,
                request_hash=_request_hash({"template_id": str(template_id)}),
            )
        response.status_code = 200
        return TemplateResponse.model_validate(template)
    async with UnitOfWork() as uow:
        service = TemplateService(uow)
        template = await service.deactivate_template(str(template_id))
    return TemplateResponse.model_validate(template)


_MAX_TEMPLATE_FILE_BYTES = 20 * 1024 * 1024


@template_jobs_router.post(
    "/api/v1/template-imports",
    response_model=TemplateImportResponse,
    status_code=202,
    responses={413: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def start_template_import(
    file: UploadFile = File(...),  # noqa: B008
    name: str = Form(...),
    document_type: str = Form(...),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> TemplateImportResponse:
    if settings.rag_profile.code != "imi_leg_06b":
        raise HTTPException(
            status_code=501, detail="Importación de plantillas no disponible"
        )
    key = _imi_idempotency_key(idempotency_key)
    filename = file.filename or "plantilla"
    data = await file.read(_MAX_TEMPLATE_FILE_BYTES + 1)
    if len(data) > _MAX_TEMPLATE_FILE_BYTES:
        raise TemplateImportInvalidError(
            "El archivo supera el límite de 20 MiB.",
            details={"field": "file", "limit_bytes": _MAX_TEMPLATE_FILE_BYTES},
        )
    body, blocks, warnings, pages_total = extract_file_content(
        filename, file.content_type, data
    )
    source_sha256, source_size, extractor_version, candidates = (
        _extraction_provenance(filename, file.content_type, data, body)
    )
    request_hash = _request_hash(
        {
            "name": name,
            "document_type": document_type,
            "filename": filename,
            "content_type": file.content_type,
            "sha256": source_sha256,
        }
    )
    async with ImiCoreUnitOfWork() as uow:
        if uow.core is None:
            raise RuntimeError("IMI_CORE_UNAVAILABLE")
        job, _created = await uow.core.create_template_import(
            name=name,
            document_type=document_type,
            filename=filename,
            content_type=file.content_type,
            source_bytes=data,
            body_template=body,
            blocks=blocks,
            warnings=warnings,
            pages_total=pages_total,
            idempotency_key=key,
            request_hash=request_hash,
            source_sha256=source_sha256,
            source_size_bytes=source_size,
            extractor_version=extractor_version,
            candidates=candidates,
        )
    return TemplateImportResponse.model_validate(job)


@template_jobs_router.get(
    "/api/v1/template-imports/{import_id}",
    response_model=TemplateImportResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_template_import(import_id: UUID) -> TemplateImportResponse:
    if settings.rag_profile.code != "imi_leg_06b":
        raise HTTPException(
            status_code=501, detail="Importación de plantillas no disponible"
        )
    async with ImiCoreUnitOfWork() as uow:
        if uow.core is None:
            raise RuntimeError("IMI_CORE_UNAVAILABLE")
        job = await uow.core.get_template_import(import_id)
    if job is None:
        raise TemplateImportNotFoundError(str(import_id))
    return TemplateImportResponse.model_validate(job)


@template_jobs_router.post(
    "/api/v1/template-imports/{import_id}/retry",
    response_model=TemplateImportResponse,
    status_code=202,
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def retry_template_import(
    import_id: UUID,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> TemplateImportResponse:
    if settings.rag_profile.code != "imi_leg_06b":
        raise HTTPException(
            status_code=501, detail="Importación de plantillas no disponible"
        )
    key = _imi_idempotency_key(idempotency_key)
    async with ImiCoreUnitOfWork() as uow:
        if uow.core is None:
            raise RuntimeError("IMI_CORE_UNAVAILABLE")
        source = await uow.core.get_template_import_source(import_id)
        if source is None:
            raise TemplateImportNotFoundError(str(import_id))
        filename, content_type, data = source
        body, blocks, warnings, pages_total = extract_file_content(
            filename, content_type, data
        )
        job, _created = await uow.core.retry_template_import(
            import_id,
            body_template=body,
            blocks=blocks,
            warnings=warnings,
            pages_total=pages_total,
            idempotency_key=key,
            request_hash=_request_hash(
                {
                    "import_id": str(import_id),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            ),
        )
    return TemplateImportResponse.model_validate(job)


@template_jobs_router.post(
    "/api/v1/template-imports/{import_id}/cancel",
    response_model=TemplateImportResponse,
    responses={404: {"model": ErrorResponse}},
)
async def cancel_template_import(
    import_id: UUID,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> TemplateImportResponse:
    if settings.rag_profile.code != "imi_leg_06b":
        raise HTTPException(
            status_code=501, detail="Importación de plantillas no disponible"
        )
    key = _imi_idempotency_key(idempotency_key)
    async with ImiCoreUnitOfWork() as uow:
        if uow.core is None:
            raise RuntimeError("IMI_CORE_UNAVAILABLE")
        job, _created = await uow.core.cancel_template_import(
            import_id,
            idempotency_key=key,
            request_hash=_request_hash({"import_id": str(import_id)}),
        )
    return TemplateImportResponse.model_validate(job)


@template_jobs_router.post(
    "/api/v1/template-imports/{import_id}/decisions",
    response_model=TemplateImportResponse,
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def save_import_decisions(
    request: Request,
    import_id: UUID,
    body: SaveImportDecisionsRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> TemplateImportResponse:
    """Persist human decisions on extraction candidates (review gate)."""
    if settings.rag_profile.code != "imi_leg_06b":
        raise HTTPException(
            status_code=501, detail="Importación de plantillas no disponible"
        )
    key = _imi_idempotency_key(idempotency_key)
    payload = body.model_dump(mode="json")
    async with ImiCoreUnitOfWork() as uow:
        if uow.core is None:
            raise RuntimeError("IMI_CORE_UNAVAILABLE")
        job, _created = await uow.core.save_import_decisions(
            import_id,
            decisions=[item.model_dump(mode="json") for item in body.decisions],
            actor=_actor(request),
            idempotency_key=key,
            request_hash=_request_hash(
                {"import_id": str(import_id), **payload}
            ),
        )
    return TemplateImportResponse.model_validate(job)


@template_jobs_router.post(
    "/api/v1/template-imports/{import_id}/promote",
    response_model=TemplateResponse,
    status_code=201,
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def promote_import_to_template(
    request: Request,
    response: Response,
    import_id: UUID,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> TemplateResponse:
    """Create a DRAFT template from a reviewed import (human approval gate)."""
    if settings.rag_profile.code != "imi_leg_06b":
        raise HTTPException(
            status_code=501, detail="Importación de plantillas no disponible"
        )
    key = _imi_idempotency_key(idempotency_key)
    async with ImiCoreUnitOfWork() as uow:
        if uow.core is None:
            raise RuntimeError("IMI_CORE_UNAVAILABLE")
        template, created = await uow.core.promote_import_to_template(
            import_id,
            actor=_actor(request),
            idempotency_key=key,
            request_hash=_request_hash({"import_id": str(import_id)}),
        )
    response.status_code = 201 if created else 200
    return TemplateResponse.model_validate(template)


@template_jobs_router.post(
    "/api/v1/template-validations",
    response_model=ValidateTemplateResponse,
    responses={422: {"model": ErrorResponse}},
)
async def validate_template_definition(
    body: ValidateTemplateRequest,
) -> ValidateTemplateResponse:
    """Validate typed fields/rules/warnings without persisting (validation gate)."""
    errors = validate_definition(
        name=body.name,
        body=body.body_template,
        fields=[item.model_dump(mode="json") for item in body.fields],
        rules=[item.model_dump(mode="json") for item in body.rules],
        blocks=[item.model_dump(mode="json") for item in body.blocks],
    )
    return ValidateTemplateResponse(errors=errors, warnings=[])


@template_jobs_router.post(
    "/api/v1/template-analyses",
    response_model=TemplateAnalysisResponse,
    status_code=202,
    responses={422: {"model": ErrorResponse}},
)
async def start_template_analysis(
    request: Request,
    body: TemplateAnalysisRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> TemplateAnalysisResponse:
    if settings.rag_profile.code != "imi_leg_06b":
        raise HTTPException(
            status_code=501, detail="Análisis de plantillas no disponible"
        )
    key = _imi_idempotency_key(idempotency_key)
    payload = body.model_dump(mode="json")
    suggestions = suggestions_for_body(body.body_template, body.fields)
    async with ImiCoreUnitOfWork() as uow:
        if uow.core is None:
            raise RuntimeError("IMI_CORE_UNAVAILABLE")
        job, _created = await uow.core.create_template_analysis(
            payload=payload,
            suggestions=suggestions,
            idempotency_key=key,
            request_hash=_request_hash(payload),
        )
    return TemplateAnalysisResponse.model_validate(job)


@template_jobs_router.get(
    "/api/v1/template-analyses/{analysis_id}",
    response_model=TemplateAnalysisResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_template_analysis(analysis_id: UUID) -> TemplateAnalysisResponse:
    if settings.rag_profile.code != "imi_leg_06b":
        raise HTTPException(
            status_code=501, detail="Análisis de plantillas no disponible"
        )
    async with ImiCoreUnitOfWork() as uow:
        if uow.core is None:
            raise RuntimeError("IMI_CORE_UNAVAILABLE")
        job = await uow.core.get_template_analysis(analysis_id)
    if job is None:
        raise TemplateAnalysisNotFoundError(str(analysis_id))
    return TemplateAnalysisResponse.model_validate(job)


@template_jobs_router.post(
    "/api/v1/template-previews",
    response_model=TemplatePreviewResponse,
    responses={422: {"model": ErrorResponse}},
)
async def preview_template(body: TemplatePreviewRequest) -> TemplatePreviewResponse:
    document, errors, warnings = preview_document(
        name=body.name,
        document_type=body.document_type,
        body=body.body_template,
        fields=body.fields,
        rules=body.rules,
        blocks=body.blocks,
        values=body.values,
    )
    return TemplatePreviewResponse(document=document, errors=errors, warnings=warnings)
