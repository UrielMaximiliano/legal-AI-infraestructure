"""Transactional IMI LEG adapter backed by the isolated core database."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from legal_ai.domain.case_file import CaseFile
from legal_ai.domain.draft import Draft
from legal_ai.domain.employee import Employee
from legal_ai.domain.enums import (
    CaseStatus,
    CaseType,
    DocumentType,
    DraftStatus,
    TemplateDocumentType,
)
from legal_ai.domain.errors import (
    ConcurrentModification004Error,
    DomainError,
    DraftDocumentLockedError,
)
from legal_ai.domain.normalization import (
    normalize_cuil,
    normalize_document_number,
    normalize_email,
    normalize_phone,
    normalize_text,
)
from legal_ai.domain.rag import RagGenerationRun
from legal_ai.domain.template import Template
from legal_ai.schemas.document import LegalDocument
from legal_ai.schemas.rag import RagStructuredDraft


class ImiConfigurationError(DomainError):
    """The IMI runtime cannot generate with an ambiguous template setup."""

    code = "IMI_CONFIGURATION_INVALID"
    status_code = 503
    default_message = "La configuración activa de IMI LEG no es válida."


class ImiCatalogValueNotFoundError(DomainError):
    """A normalized employee catalog value is not configured in IMI Core."""

    code = "IMI_CATALOG_VALUE_NOT_FOUND"
    status_code = 422
    default_message = "El valor de catálogo solicitado no existe o está inactivo."

    def __init__(self, field: str, value: str) -> None:
        super().__init__(details={"field": field, "value": value})


def _enum_value(value: str, mapping: dict[str, str], fallback: str) -> str:
    return mapping.get(value.upper(), fallback)


def _decode_variable_value(value: Any) -> str:
    """Return a stored JSONB variable as the original string value."""

    decoded: object = value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            decoded = value
    if decoded is None:
        return ""
    if isinstance(decoded, str):
        return decoded
    return str(decoded)


class ImiCoreRepository:
    """Explicit repository for core tables; it never imports legacy ORM models."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_template(self, template_id: uuid.UUID) -> Template | None:
        result = await self._session.execute(
            text(
                """
                SELECT
                  t.id, t.name, t.active, t.created_at,
                  t.organization_id, t.jurisdiction, t.language_code,
                  dt.code AS document_type,
                  v.version, v.body_template, v.description,
                  org.name AS organization_name,
                  COALESCE(
                    array_agg(tv.variable_key ORDER BY tv.display_order)
                    FILTER (WHERE tv.variable_key IS NOT NULL AND tv.required),
                    ARRAY[]::varchar[]
                  ) AS variables
                FROM imi.document_templates AS t
                JOIN imi.document_types AS dt ON dt.id = t.document_type_id
                JOIN imi.organizations AS org ON org.id = t.organization_id
                JOIN imi.document_template_versions AS v
                  ON v.template_id = t.id
                 AND v.version = (
                   SELECT max(v2.version)
                   FROM imi.document_template_versions AS v2
                   WHERE v2.template_id = t.id
                 )
                LEFT JOIN imi.template_variables AS tv
                  ON tv.template_version_id = v.id
                WHERE t.id = :template_id
                GROUP BY t.id, dt.code, v.version, v.body_template,
                         v.description, org.name
                """
            ),
            {"template_id": template_id},
        )
        row = result.mappings().first()
        return self._template_from_row(row) if row else None

    async def list_templates(
        self,
        document_type: str | None,
        search: str | None,
        skip: int,
        limit: int,
    ) -> tuple[list[Template], int]:
        clauses = ["t.active", "org.code = 'IMI'"]
        params: dict[str, Any] = {"skip": skip, "limit": limit}
        if document_type:
            clauses.append("lower(dt.code) = lower(:document_type)")
            params["document_type"] = document_type
        if search:
            clauses.append("t.name ILIKE :search")
            params["search"] = f"%{search}%"
        where = " AND ".join(clauses)
        count = await self._session.execute(
            text(
                f"""
                SELECT count(*)
                FROM imi.document_templates AS t
                JOIN imi.document_types AS dt ON dt.id = t.document_type_id
                JOIN imi.organizations AS org ON org.id = t.organization_id
                WHERE {where}
                """
            ),
            params,
        )
        total = int(count.scalar_one())
        rows = await self._session.execute(
            text(
                f"""
                SELECT t.id
                FROM imi.document_templates AS t
                JOIN imi.document_types AS dt ON dt.id = t.document_type_id
                JOIN imi.organizations AS org ON org.id = t.organization_id
                WHERE {where}
                ORDER BY t.created_at DESC, t.id DESC
                OFFSET :skip LIMIT :limit
                """
            ),
            params,
        )
        items: list[Template] = []
        for row in rows:
            template = await self.get_template(row[0])
            if template is not None:
                items.append(template)
        return items, total

    async def get_employee(self, employee_id: uuid.UUID) -> Employee | None:
        result = await self._session.execute(
            text(
                """
                SELECT e.*, p.name AS position_name, ou.name AS department_name
                FROM imi.employees AS e
                LEFT JOIN imi.positions AS p ON p.id = e.position_id
                LEFT JOIN imi.organizational_units AS ou
                  ON ou.id = e.organizational_unit_id
                WHERE e.id = :employee_id
                """
            ),
            {"employee_id": employee_id},
        )
        row = result.mappings().first()
        return self._employee_from_row(row) if row else None

    async def create_employee(
        self,
        *,
        employee_number: str,
        first_name: str,
        last_name: str,
        document_type: DocumentType,
        document_number: str,
        cuil: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        position: str | None = None,
        department: str | None = None,
    ) -> Employee:
        """Create an employee in the normalized IMI Core database."""

        normalized_employee_number = normalize_text(employee_number)
        normalized_first_name = normalize_text(first_name)
        normalized_last_name = normalize_text(last_name)
        normalized_document_number = normalize_document_number(
            document_type, document_number
        )
        normalized_cuil = normalize_cuil(cuil) if cuil else None
        normalized_email = normalize_email(email) if email else None
        normalized_phone = normalize_phone(phone) if phone else None

        existing_number = await self._session.execute(
            text(
                "SELECT 1 FROM imi.employees "
                "WHERE employee_number = :employee_number"
            ),
            {"employee_number": normalized_employee_number},
        )
        if existing_number.first() is not None:
            from legal_ai.application.employee_service import (
                EmployeeNumberConflictError,
            )

            raise EmployeeNumberConflictError(normalized_employee_number)

        existing_document = await self._session.execute(
            text(
                "SELECT 1 FROM imi.employees "
                "WHERE identity_document_type_code = :document_type "
                "AND identity_document_number = :document_number"
            ),
            {
                "document_type": document_type.value.upper(),
                "document_number": normalized_document_number,
            },
        )
        if existing_document.first() is not None:
            from legal_ai.application.employee_service import (
                EmployeeDocumentConflictError,
            )

            raise EmployeeDocumentConflictError("document_number", "document_number")

        position_id = await self._catalog_id(
            "positions", position, field="position"
        )
        organizational_unit_id = await self._catalog_id(
            "organizational_units", department, field="department"
        )

        employee_id = uuid.uuid4()
        await self._session.execute(
            text(
                """
                INSERT INTO imi.employees (
                  id, employee_number, first_name, last_name,
                  identity_document_type_code, identity_document_number,
                  cuil, email, phone, position_id, organizational_unit_id,
                  active
                ) VALUES (
                  :id, :employee_number, :first_name, :last_name,
                  :document_type, :document_number,
                  :cuil, :email, :phone, :position_id, :organizational_unit_id,
                  true
                )
                """
            ),
            {
                "id": employee_id,
                "employee_number": normalized_employee_number,
                "first_name": normalized_first_name,
                "last_name": normalized_last_name,
                "document_type": document_type.value.upper(),
                "document_number": normalized_document_number,
                "cuil": normalized_cuil,
                "email": normalized_email,
                "phone": normalized_phone,
                "position_id": position_id,
                "organizational_unit_id": organizational_unit_id,
            },
        )
        employee = await self.get_employee(employee_id)
        if employee is None:
            raise RuntimeError("IMI_EMPLOYEE_CREATE_FAILED")
        return employee

    async def _catalog_id(
        self,
        table: str,
        value: str | None,
        *,
        field: str,
    ) -> uuid.UUID | None:
        """Resolve an active normalized catalog value without denormalizing it."""

        if value is None:
            return None
        normalized_value = normalize_text(value)
        result = await self._session.execute(
            text(
                f"SELECT id FROM imi.{table} "
                "WHERE active AND (lower(code) = lower(:value) "
                "OR lower(name) = lower(:value))"
            ),
            {"value": normalized_value},
        )
        catalog_id = result.scalar_one_or_none()
        if catalog_id is None:
            raise ImiCatalogValueNotFoundError(field, normalized_value)
        return cast("uuid.UUID", catalog_id)

    async def list_employees(
        self,
        page: int,
        page_size: int,
        query: str | None = None,
        active: bool | None = None,
        department: str | None = None,
    ) -> tuple[list[Employee], int]:
        clauses = ["1=1"]
        params: dict[str, Any] = {
            "offset": (page - 1) * page_size,
            "limit": page_size,
        }
        if query:
            clauses.append(
                "(e.employee_number ILIKE :query OR e.first_name ILIKE :query "
                "OR e.last_name ILIKE :query "
                "OR e.identity_document_number ILIKE :query)"
            )
            params["query"] = f"%{query}%"
        if active is not None:
            clauses.append("e.active = :active")
            params["active"] = active
        if department:
            clauses.append("ou.name ILIKE :department")
            params["department"] = f"%{department}%"
        where = " AND ".join(clauses)
        count = await self._session.execute(
            text(
                f"""
                SELECT count(*) FROM imi.employees AS e
                LEFT JOIN imi.organizational_units AS ou
                  ON ou.id = e.organizational_unit_id
                WHERE {where}
                """
            ),
            params,
        )
        total = int(count.scalar_one())
        rows = await self._session.execute(
            text(
                f"""
                SELECT e.*, p.name AS position_name, ou.name AS department_name
                FROM imi.employees AS e
                LEFT JOIN imi.positions AS p ON p.id = e.position_id
                LEFT JOIN imi.organizational_units AS ou
                  ON ou.id = e.organizational_unit_id
                WHERE {where}
                ORDER BY e.created_at DESC, e.id DESC
                OFFSET :offset LIMIT :limit
                """
            ),
            params,
        )
        return [self._employee_from_row(row) for row in rows.mappings()], total

    async def get_case_file(self, case_file_id: uuid.UUID) -> CaseFile | None:
        result = await self._session.execute(
            text(
                """
                SELECT cf.*, ct.code AS case_type_code
                FROM imi.case_files AS cf
                JOIN imi.case_types AS ct ON ct.id = cf.case_type_id
                WHERE cf.id = :case_file_id
                """
            ),
            {"case_file_id": case_file_id},
        )
        row = result.mappings().first()
        return self._case_file_from_row(row) if row else None

    async def create_case_file(
        self,
        *,
        employee_id: uuid.UUID | None,
        title: str,
        case_type: CaseType,
        description: str | None = None,
        case_number: str | None = None,
        request_id: str | None = None,
    ) -> CaseFile:
        """Create an IMI case file and its initial status history atomically."""

        from legal_ai.application.case_file_service import (
            CaseFileEmployeeInactiveError,
            CaseFileEmployeeNotFoundError,
        )

        if employee_id is not None:
            employee = await self.get_employee(employee_id)
            if employee is None:
                raise CaseFileEmployeeNotFoundError(employee_id)
            if not employee.active:
                raise CaseFileEmployeeInactiveError(employee_id)

        normalized_title = normalize_text(title)
        normalized_description = description.strip() if description else None
        case_type_code = case_type.value.upper()
        case_type_result = await self._session.execute(
            text("SELECT code FROM imi.case_types WHERE code = :case_type AND active"),
            {"case_type": case_type_code},
        )
        if case_type_result.scalar_one_or_none() is None:
            raise ImiCatalogValueNotFoundError("case_type", case_type.value)

        case_file_id = uuid.uuid4()
        now = datetime.now(UTC)
        normalized_case_number = (
            normalize_text(case_number) if case_number else f"CF-{case_file_id}"
        )
        await self._session.execute(
            text(
                """
                INSERT INTO imi.case_files (
                  id, case_number, employee_id, case_type_id, status_code,
                  title, description, opened_at, created_at, updated_at
                )
                SELECT
                  :id, :case_number, :employee_id, ct.id, 'DRAFT',
                  :title, :description, :now, :now, :now
                FROM imi.case_types AS ct
                WHERE ct.code = :case_type AND ct.active
                """
            ),
            {
                "id": case_file_id,
                "case_number": normalized_case_number,
                "employee_id": employee_id,
                "case_type": case_type_code,
                "title": normalized_title,
                "description": normalized_description,
                "now": now,
            },
        )
        await self._session.execute(
            text(
                """
                INSERT INTO imi.case_status_history (
                  id, case_file_id, from_status_code, to_status_code,
                  changed_at, changed_by_auth_user_id, request_id
                ) VALUES (
                  :id, :case_file_id, NULL, 'DRAFT',
                  :now, 'system', :request_id
                )
                """
            ),
            {
                "id": uuid.uuid4(),
                "case_file_id": case_file_id,
                "now": now,
                "request_id": request_id,
            },
        )
        case_file = await self.get_case_file(case_file_id)
        if case_file is None:
            raise RuntimeError("IMI_CASE_FILE_CREATE_FAILED")
        return case_file

    async def list_case_files(
        self,
        page: int,
        page_size: int,
        query: str | None = None,
        employee_id: uuid.UUID | None = None,
        status: str | None = None,
        case_type: str | None = None,
    ) -> tuple[list[CaseFile], int]:
        clauses = ["1=1"]
        params: dict[str, Any] = {
            "offset": (page - 1) * page_size,
            "limit": page_size,
        }
        if query:
            clauses.append("(cf.case_number ILIKE :query OR cf.title ILIKE :query)")
            params["query"] = f"%{query}%"
        if employee_id:
            clauses.append("cf.employee_id = :employee_id")
            params["employee_id"] = employee_id
        if status:
            clauses.append("lower(cf.status_code) = lower(:status)")
            params["status"] = status
        if case_type:
            clauses.append("lower(ct.code) = lower(:case_type)")
            params["case_type"] = case_type
        where = " AND ".join(clauses)
        count = await self._session.execute(
                text(
                    f"""
                    SELECT count(*) FROM imi.case_files AS cf
                    JOIN imi.case_types AS ct ON ct.id = cf.case_type_id
                    WHERE {where}
                    """
                ),
                params,
        )
        total = int(count.scalar_one())
        rows = await self._session.execute(
            text(
                f"""
                SELECT cf.*, ct.code AS case_type_code
                FROM imi.case_files AS cf
                JOIN imi.case_types AS ct ON ct.id = cf.case_type_id
                WHERE {where}
                ORDER BY cf.created_at DESC, cf.id DESC
                OFFSET :offset LIMIT :limit
                """
            ),
            params,
        )
        return [self._case_file_from_row(row) for row in rows.mappings()], total

    async def list_drafts(
        self,
        *,
        page: int,
        page_size: int,
        query: str | None = None,
        document_type: str | None = None,
        case_file_id: uuid.UUID | None = None,
    ) -> tuple[list[Draft], int]:
        """List IMI documents from the core database with stable pagination."""

        clauses = ["1=1"]
        params: dict[str, Any] = {
            "offset": (page - 1) * page_size,
            "limit": page_size,
        }
        if query:
            clauses.append("(d.title ILIKE :query OR cf.case_number ILIKE :query)")
            params["query"] = f"%{query}%"
        if document_type:
            clauses.append("lower(dt.code) = lower(:document_type)")
            params["document_type"] = document_type
        if case_file_id:
            clauses.append("d.case_file_id = :case_file_id")
            params["case_file_id"] = case_file_id
        where = " AND ".join(clauses)
        count = await self._session.execute(
            text(
                f"""
                SELECT count(*)
                FROM imi.documents AS d
                JOIN imi.case_files AS cf ON cf.id = d.case_file_id
                JOIN imi.document_template_versions AS tv
                  ON tv.id = d.template_version_id
                JOIN imi.document_templates AS t ON t.id = tv.template_id
                JOIN imi.document_types AS dt ON dt.id = t.document_type_id
                WHERE {where}
                """
            ),
            params,
        )
        total = int(count.scalar_one())
        rows = await self._session.execute(
            text(
                f"""
                SELECT d.id
                FROM imi.documents AS d
                JOIN imi.case_files AS cf ON cf.id = d.case_file_id
                JOIN imi.document_template_versions AS tv
                  ON tv.id = d.template_version_id
                JOIN imi.document_templates AS t ON t.id = tv.template_id
                JOIN imi.document_types AS dt ON dt.id = t.document_type_id
                WHERE {where}
                ORDER BY d.updated_at DESC, d.id DESC
                OFFSET :offset LIMIT :limit
                """
            ),
            params,
        )
        items: list[Draft] = []
        for row in rows:
            draft = await self.get_draft(row[0])
            if draft is not None:
                items.append(draft)
        return items, total

    async def save_generation_outcome(
        self,
        outcome: Any,
        *,
        request_id: str,
    ) -> tuple[uuid.UUID, uuid.UUID]:
        """Persist a generated structured document and its core audit rows."""

        run: RagGenerationRun = outcome.run
        draft: Draft = outcome.draft
        structured: RagStructuredDraft = outcome.structured_draft
        version_row = await self._session.execute(
            text(
                """
                SELECT v.id
                FROM imi.document_template_versions AS v
                JOIN imi.document_templates AS t ON t.id = v.template_id
                WHERE t.id = :template_id AND t.active
                ORDER BY v.version DESC LIMIT 1
                """
            ),
            {"template_id": run.template_id},
        )
        template_version_id = version_row.scalar_one_or_none()
        if template_version_id is None:
            raise ImiConfigurationError(details={"template_id": str(run.template_id)})

        content_json = structured.model_dump(mode="json")
        content_text = draft.content or structured.render_for_review()
        content_hash = _sha256_text(content_text)
        await self._session.execute(
            text(
                """
                INSERT INTO imi.documents (
                  id, case_file_id, template_version_id, title, status_code,
                  current_version, created_by_auth_user_id
                ) VALUES (
                  :id, :case_file_id, :template_version_id, :title, 'DRAFT', 1,
                  'rag-system'
                ) ON CONFLICT (id) DO NOTHING
                """
            ),
            {
                "id": draft.id,
                "case_file_id": draft.case_file_id,
                "template_version_id": template_version_id,
                "title": draft.title,
            },
        )
        version_id = uuid.uuid4()
        await self._session.execute(
            text(
                """
                INSERT INTO imi.document_versions (
                  id, document_id, version, source_code, content_json,
                  content_text, content_sha256, edited_by_auth_user_id
                ) VALUES (
                  :id, :document_id, 1, 'AI', CAST(:content_json AS jsonb),
                  :content_text, :content_sha256, 'rag-system'
                ) ON CONFLICT (document_id, version) DO NOTHING
                """
            ),
            {
                "id": version_id,
                "document_id": draft.id,
                "content_json": json.dumps(content_json, ensure_ascii=False),
                "content_text": content_text,
                "content_sha256": content_hash,
            },
        )
        existing_version = await self._session.execute(
            text(
                "SELECT id FROM imi.document_versions "
                "WHERE document_id = :document_id AND version = 1"
            ),
            {"document_id": draft.id},
        )
        version_id = existing_version.scalar_one()

        await self._session.execute(
            text(
                """
                INSERT INTO imi.generation_operations (
                  id, case_file_id, template_version_id, mode, idempotency_key,
                  request_hash, request_id, status_code, rag_run_id, document_id,
                  finished_at
                ) VALUES (
                  :id, :case_file_id, :template_version_id, 'AI', :idempotency_key,
                  :request_hash, :request_id, 'SUCCEEDED', :rag_run_id, :document_id,
                  now()
                ) ON CONFLICT (id) DO NOTHING
                """
            ),
            {
                "id": run.id,
                "case_file_id": draft.case_file_id,
                "template_version_id": template_version_id,
                "idempotency_key": run.idempotency_key_hash or str(run.id),
                "request_hash": run.request_hash,
                "request_id": request_id,
                "rag_run_id": run.id,
                "document_id": draft.id,
            },
        )
        await self._session.execute(
            text(
                """
                INSERT INTO imi.generation_attempts (
                  operation_id, attempt_number, model, prompt_sha256,
                  status_code, finished_at
                ) VALUES (:operation_id, 1, :model, :prompt_sha256, 'SUCCEEDED', now())
                ON CONFLICT (operation_id, attempt_number) DO NOTHING
                """
            ),
            {
                "operation_id": run.id,
                "model": run.generation_model,
                "prompt_sha256": run.prompt_hash,
            },
        )
        for source in structured.sources:
            matching = next(
                (
                    item
                    for item in outcome.sources
                    if item.citation_id == source.citation_id
                ),
                None,
            )
            if matching is None:
                continue
            await self._session.execute(
                text(
                    """
                    INSERT INTO imi.document_citations (
                      document_version_id, citation_id, rag_run_id,
                      source_document_external_id, source_chunk_external_id
                    ) VALUES (
                      :version_id, :citation_id, :rag_run_id, :external_id,
                      :chunk_id
                    )
                    ON CONFLICT (document_version_id, citation_id) DO NOTHING
                    """
                ),
                {
                    "version_id": version_id,
                    "citation_id": source.citation_id,
                    "rag_run_id": run.id,
                    "external_id": matching.external_id,
                    "chunk_id": matching.chunk_id,
                },
            )
        await self._session.execute(
            text(
                """
                INSERT INTO audit.events (
                  event_type, entity_type, entity_id, actor_auth_user_id,
                  request_id, summary_json
                )
                VALUES (
                  'RAG_GENERATION_SUCCEEDED', 'DOCUMENT', :entity_id,
                  'rag-system', :request_id, CAST(:summary AS jsonb)
                )
                """
            ),
            {
                "entity_id": draft.id,
                "request_id": request_id,
                "summary": json.dumps(
                    {
                        "profile_code": run.profile_code,
                        "rag_run_id": str(run.id),
                        "source_count": len(structured.sources),
                        "schema_version": structured.schema_version,
                    }
                ),
            },
        )
        return draft.id, version_id

    async def create_manual_draft(
        self,
        *,
        template_id: uuid.UUID,
        case_file_id: uuid.UUID,
        variables: dict[str, str],
        document: LegalDocument,
        actor: str,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
    ) -> Draft:
        """Create a manual draft in the isolated IMI Core database."""

        from legal_ai.application.draft_service import (
            CaseFileNotFoundError,
            TemplateInactiveError,
            TemplateNotFoundError,
        )
        from legal_ai.domain.errors import (
            IdempotencyConflictError,
            StructuredDocumentInvalidError,
        )

        existing = await self._session.execute(
            text(
                """
                SELECT request_hash, document_id
                FROM imi.generation_operations
                WHERE idempotency_key = :idempotency_key
                FOR UPDATE
                """
            ),
            {"idempotency_key": idempotency_key},
        )
        existing_row = existing.mappings().first()
        if existing_row is not None:
            if existing_row["request_hash"] != request_hash:
                raise IdempotencyConflictError()
            if existing_row["document_id"] is None:
                raise ImiConfigurationError(
                    details={"idempotency_key": idempotency_key}
                )
            draft = await self.get_draft(existing_row["document_id"])
            if draft is None:
                raise ImiConfigurationError(
                    details={"idempotency_key": idempotency_key}
                )
            return draft

        template = await self.get_template(template_id)
        if template is None:
            raise TemplateNotFoundError(str(template_id))
        if not template.is_active:
            raise TemplateInactiveError(str(template_id))
        if document.document_type != str(template.document_type):
            raise StructuredDocumentInvalidError(details={"field": "document_type"})
        if await self.get_case_file(case_file_id) is None:
            raise CaseFileNotFoundError(str(case_file_id))

        template_version = await self._session.execute(
            text(
                """
                SELECT v.id
                FROM imi.document_template_versions AS v
                WHERE v.template_id = :template_id
                ORDER BY v.version DESC
                LIMIT 1
                """
            ),
            {"template_id": template_id},
        )
        template_version_id = template_version.scalar_one_or_none()
        if template_version_id is None:
            raise ImiConfigurationError(details={"template_id": str(template_id)})

        now = datetime.now(UTC)
        document_id = uuid.uuid4()
        title = document.title.strip() or template.name
        content_json = document.model_dump(mode="json")
        content_text = document.render()
        content_hash = _sha256_text(content_text)
        await self._session.execute(
            text(
                """
                INSERT INTO imi.documents (
                  id, case_file_id, template_version_id, title, status_code,
                  current_version, created_by_auth_user_id, created_at, updated_at
                ) VALUES (
                  :id, :case_file_id, :template_version_id, :title, 'DRAFT',
                  1, :actor, :now, :now
                )
                """
            ),
            {
                "id": document_id,
                "case_file_id": case_file_id,
                "template_version_id": template_version_id,
                "title": title,
                "actor": actor,
                "now": now,
            },
        )
        version_id = uuid.uuid4()
        await self._session.execute(
            text(
                """
                INSERT INTO imi.document_versions (
                  id, document_id, version, source_code, content_json,
                  content_text, content_sha256, edited_by_auth_user_id,
                  created_at
                ) VALUES (
                  :id, :document_id, 1, 'MANUAL', CAST(:content_json AS jsonb),
                  :content_text, :content_sha256, :actor, :now
                )
                """
            ),
            {
                "id": version_id,
                "document_id": document_id,
                "content_json": json.dumps(content_json, ensure_ascii=False),
                "content_text": content_text,
                "content_sha256": content_hash,
                "actor": actor,
                "now": now,
            },
        )

        variable_rows = await self._session.execute(
            text(
                """
                SELECT id, variable_key
                FROM imi.template_variables
                WHERE template_version_id = :template_version_id
                ORDER BY display_order
                """
            ),
            {"template_version_id": template_version_id},
        )
        for variable_row in variable_rows.mappings():
            key = variable_row["variable_key"]
            if key not in variables:
                continue
            await self._session.execute(
                text(
                    """
                    INSERT INTO imi.document_variable_values (
                      document_version_id, template_variable_id, value_json
                    ) VALUES (
                      :document_version_id, :template_variable_id,
                      CAST(:value_json AS jsonb)
                    )
                    """
                ),
                {
                    "document_version_id": version_id,
                    "template_variable_id": variable_row["id"],
                    "value_json": json.dumps(variables[key], ensure_ascii=False),
                },
            )

        operation_id = uuid.uuid4()
        await self._session.execute(
            text(
                """
                INSERT INTO imi.generation_operations (
                  id, case_file_id, template_version_id, mode, idempotency_key,
                  request_hash, request_id, status_code, document_id, finished_at
                ) VALUES (
                  :id, :case_file_id, :template_version_id, 'MANUAL',
                  :idempotency_key, :request_hash, :request_id, 'SUCCEEDED',
                  :document_id, :now
                )
                """
            ),
            {
                "id": operation_id,
                "case_file_id": case_file_id,
                "template_version_id": template_version_id,
                "idempotency_key": idempotency_key,
                "request_hash": request_hash,
                "request_id": request_id,
                "document_id": document_id,
                "now": now,
            },
        )
        await self._session.execute(
            text(
                """
                INSERT INTO imi.generation_attempts (
                  operation_id, attempt_number, status_code, finished_at
                ) VALUES (:operation_id, 1, 'SUCCEEDED', :now)
                """
            ),
            {"operation_id": operation_id, "now": now},
        )
        await self._session.execute(
            text(
                """
                INSERT INTO audit.events (
                  event_type, entity_type, entity_id, actor_auth_user_id,
                  request_id, summary_json
                ) VALUES (
                  'MANUAL_DRAFT_CREATED', 'DOCUMENT', :entity_id, :actor,
                  :request_id, CAST(:summary AS jsonb)
                )
                """
            ),
            {
                "entity_id": document_id,
                "actor": actor,
                "request_id": request_id,
                "summary": json.dumps(
                    {
                        "template_id": str(template_id),
                        "source_code": "MANUAL",
                    }
                ),
            },
        )
        draft = await self.get_draft(document_id)
        if draft is None:
            raise RuntimeError("IMI_MANUAL_DRAFT_CREATE_FAILED")
        return draft

    async def get_draft(self, draft_id: uuid.UUID) -> Draft | None:
        result = await self._session.execute(
            text(
                """
                SELECT d.*, dv.version, dv.source_code, dv.content_json,
                       dv.content_text,
                       dv.content_sha256, dv.created_at AS version_created_at,
                       t.id AS template_id, dt.code AS document_type
                FROM imi.documents AS d
                JOIN imi.document_template_versions AS tv
                  ON tv.id = d.template_version_id
                JOIN imi.document_templates AS t ON t.id = tv.template_id
                JOIN imi.document_types AS dt ON dt.id = t.document_type_id
                JOIN imi.document_versions AS dv
                  ON dv.document_id = d.id AND dv.version = d.current_version
                WHERE d.id = :draft_id
                """
            ),
            {"draft_id": draft_id},
        )
        row = result.mappings().first()
        if row is None:
            return None
        variable_result = await self._session.execute(
            text(
                """
                SELECT tv.variable_key, dvv.value_json
                FROM imi.document_variable_values AS dvv
                JOIN imi.template_variables AS tv
                  ON tv.id = dvv.template_variable_id
                JOIN imi.document_versions AS dv
                  ON dv.id = dvv.document_version_id
                WHERE dv.document_id = :draft_id
                  AND dv.version = :version
                ORDER BY tv.display_order
                """
            ),
            {"draft_id": draft_id, "version": row["version"]},
        )
        variables_used = {
            str(variable_row["variable_key"]): _decode_variable_value(
                variable_row["value_json"]
            )
            for variable_row in variable_result.mappings()
        }
        return Draft(
            id=row["id"],
            template_id=row["template_id"],
            case_file_id=row["case_file_id"],
            title=row["title"],
            status=DraftStatus.GENERADO,
            version=row["version"],
            generation_number=1,
            context_snapshot={
                "profile_code": "imi_leg_06b",
                "source_code": row["source_code"],
            },
            context_hash=row["content_sha256"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            content=row["content_text"],
            document=row["content_json"],
            document_type=_enum_value(
                str(row["document_type"]),
                {"DISPOSICION": "disposicion", "NOTA_INICIO": "nota_inicio"},
                "disposicion",
            ),
            variables_used=variables_used,
        )

    async def update_document(
        self,
        *,
        draft_id: uuid.UUID,
        expected_version: int,
        document: LegalDocument,
        actor: str,
    ) -> Draft | None:
        """Persist an IMI document edit as the next optimistic-lock version."""
        current_result = await self._session.execute(
            text(
                """
                SELECT d.current_version, d.status_code
                FROM imi.documents AS d
                WHERE d.id = :draft_id
                FOR UPDATE
                """
            ),
            {"draft_id": draft_id},
        )
        current = current_result.mappings().first()
        if current is None:
            return None
        if int(current["current_version"]) != expected_version:
            raise ConcurrentModification004Error(details={"draft_id": str(draft_id)})
        if current["status_code"] in {"IN_REVIEW", "APPROVED", "FINALIZED"}:
            raise DraftDocumentLockedError()

        review_result = await self._session.execute(
            text(
                """
                SELECT 1
                FROM imi.document_reviews AS r
                JOIN imi.document_versions AS v
                  ON v.id = r.document_version_id
                WHERE v.document_id = :draft_id
                  AND v.version = :expected_version
                  AND r.status_code IN ('IN_REVIEW', 'APPROVED', 'FINALIZED')
                LIMIT 1
                """
            ),
            {"draft_id": draft_id, "expected_version": expected_version},
        )
        if review_result.first() is not None:
            raise DraftDocumentLockedError()

        now = datetime.now(UTC)
        new_version = expected_version + 1
        content_text = document.render()
        content_json = json.dumps(document.model_dump(mode="json"), ensure_ascii=False)
        content_hash = _sha256_text(content_text)
        await self._session.execute(
            text(
                """
                UPDATE imi.documents
                SET title = :title, current_version = :new_version, updated_at = :now
                WHERE id = :draft_id AND current_version = :expected_version
                """
            ),
            {
                "draft_id": draft_id,
                "title": document.title.strip(),
                "new_version": new_version,
                "expected_version": expected_version,
                "now": now,
            },
        )
        await self._session.execute(
            text(
                """
                INSERT INTO imi.document_versions (
                  document_id, version, source_code, content_json, content_text,
                  content_sha256, edited_by_auth_user_id
                ) VALUES (
                  :document_id, :version, 'EDITED', CAST(:content_json AS jsonb),
                  :content_text, :content_sha256, :actor
                )
                """
            ),
            {
                "document_id": draft_id,
                "version": new_version,
                "content_json": content_json,
                "content_text": content_text,
                "content_sha256": content_hash,
                "actor": actor,
            },
        )
        # A content edit creates a new immutable version.  Carry the
        # structured template values forward so rendering the current version
        # does not lose legal metadata such as date, amount or beneficiary.
        await self._session.execute(
            text(
                """
                INSERT INTO imi.document_variable_values (
                  document_version_id, template_variable_id, value_json
                )
                SELECT new_version.id, previous_values.template_variable_id,
                       previous_values.value_json
                FROM imi.document_variable_values AS previous_values
                JOIN imi.document_versions AS previous_version
                  ON previous_version.id = previous_values.document_version_id
                JOIN imi.document_versions AS new_version
                  ON new_version.document_id = previous_version.document_id
                 AND new_version.version = :new_version
                WHERE previous_version.document_id = :draft_id
                  AND previous_version.version = :expected_version
                """
            ),
            {
                "draft_id": draft_id,
                "expected_version": expected_version,
                "new_version": new_version,
            },
        )
        await self._session.execute(
            text(
                """
                INSERT INTO imi.document_transitions (
                  document_id, from_status_code, to_status_code, action,
                  performed_by_auth_user_id
                ) VALUES (
                  :document_id, :status_code, :status_code, 'EDIT_CONTENT', :actor
                )
                """
            ),
            {
                "document_id": draft_id,
                "status_code": current["status_code"],
                "actor": actor,
            },
        )
        return await self.get_draft(draft_id)

    @staticmethod
    def _template_from_row(row: Any) -> Template:
        document_type = _enum_value(
            str(row["document_type"]),
            {"DISPOSICION": "disposicion", "NOTA_INICIO": "nota_inicio"},
            "disposicion",
        )
        return Template(
            id=row["id"],
            name=row["name"],
            document_type=TemplateDocumentType(document_type),
            version=row["version"],
            body_template=row["body_template"],
            is_active=row["active"],
            created_at=row["created_at"],
            updated_at=row["created_at"],
            organ_emisor=row["organization_name"],
            normativa=None,
            description=row["description"],
            variables=list(row["variables"] or []),
        )

    @staticmethod
    def _employee_from_row(row: Any) -> Employee:
        document_type = _enum_value(
            str(row["identity_document_type_code"]),
            {"DNI": "dni", "PASSPORT": "pasaporte"},
            "dni",
        )
        return Employee(
            id=row["id"],
            employee_number=row["employee_number"],
            first_name=row["first_name"],
            last_name=row["last_name"],
            document_type=DocumentType(document_type),
            document_number=row["identity_document_number"],
            cuil=row["cuil"],
            email=row["email"],
            phone=row["phone"],
            position=row.get("position_name"),
            department=row.get("department_name"),
            active=row["active"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _case_file_from_row(row: Any) -> CaseFile:
        status = _enum_value(
            str(row["status_code"]),
            {"DRAFT": "draft", "OPEN": "in_process", "CLOSED": "archived"},
            "draft",
        )
        case_type = _enum_value(
            str(row.get("case_type_code", "OTRO")),
            {"OTRO": "otro"},
            "otro",
        )
        return CaseFile(
            id=row["id"],
            case_number=row["case_number"],
            employee_id=row["employee_id"],
            title=row["title"],
            description=row["description"],
            case_type=CaseType(case_type),
            status=CaseStatus(status),
            version=1,
            opened_at=row["opened_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            closed_at=row["closed_at"],
        )


class ImiCoreUnitOfWork:
    """Unit of work that can only reach the IMI core database."""

    def __init__(self) -> None:
        from legal_ai.adapters.database.engine import get_session_factory

        self._session_factory = get_session_factory("core")
        self._session: AsyncSession | None = None
        self.core: ImiCoreRepository | None = None

    async def __aenter__(self) -> ImiCoreUnitOfWork:
        self._session = self._session_factory()
        await self._session.begin()
        self.core = ImiCoreRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        if self._session is None:
            return
        try:
            if exc_type is None:
                await self._session.commit()
            else:
                await self._session.rollback()
        finally:
            await self._session.close()
            self._session = None

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("ImiCoreUnitOfWork not initialized")
        return self._session


def _sha256_text(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()
