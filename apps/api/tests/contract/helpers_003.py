"""Real PostgreSQL fixtures shared by increment 003 contract tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.domain.case_file import CaseFile
from legal_ai.domain.designation_data import DesignationData
from legal_ai.domain.employee import Employee
from legal_ai.domain.enums import (
    CaseStatus,
    CaseType,
    DocumentType,
    TemplateDocumentType,
)
from legal_ai.domain.template import Template


async def seed_case_and_template(
    *,
    with_designation: bool = True,
    case_type: CaseType | None = None,
    body_template: str = "Hola {{employee.first_name}}",
    variables: list[str] | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Create a unique case file and template through the real UoW."""
    now = datetime.now(UTC)
    employee_id = uuid.uuid4()
    case_file_id = uuid.uuid4()
    template_id = uuid.uuid4()
    async with UnitOfWork() as uow:
        await uow.employees.create(
            Employee(
                id=employee_id,
                employee_number=f"LEG-{uuid.uuid4().hex[:10]}",
                first_name="Contrato",
                last_name="003",
                document_type=DocumentType.DNI,
                document_number=str(uuid.uuid4().int)[:8],
                department="Legal",
                created_at=now,
                updated_at=now,
            )
        )
        await uow.case_files.create(
            CaseFile(
                id=case_file_id,
                case_number=f"EXP-{uuid.uuid4().hex[:10]}",
                employee_id=employee_id,
                title="Caso contractual 003",
                case_type=case_type
                or (CaseType.DESIGNACION if with_designation else CaseType.OTRO),
                status=CaseStatus.DRAFT,
                opened_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        if with_designation:
            await uow.designations.create(
                DesignationData(
                    id=uuid.uuid4(),
                    case_file_id=case_file_id,
                    position_name="Director",
                    organizational_unit="Unidad Legal",
                    created_at=now,
                    updated_at=now,
                )
            )
        await uow.templates.create(
            Template(
                id=template_id,
                name=f"Contrato-{uuid.uuid4().hex[:10]}",
                document_type=TemplateDocumentType.RESOLUCION,
                version=1,
                body_template=body_template,
                variables=variables or [],
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        )
    return case_file_id, template_id
