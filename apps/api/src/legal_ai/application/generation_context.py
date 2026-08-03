"""Generation context builder."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from legal_ai.adapters.database.unit_of_work import UnitOfWork

ContextSnapshot = dict[str, object]


class ContextBuildFailedError(Exception):
    """Failed to build generation context."""

    def __init__(self, message: str = "Failed to build context") -> None:
        super().__init__(message)


class MissingRequiredVariablesError(Exception):
    """Missing required variables for template."""

    def __init__(self, missing: list[str]) -> None:
        self.missing = missing
        super().__init__(f"Missing required variables: {', '.join(missing)}")


class DesignationDataIncompleteError(Exception):
    """Designation data is incomplete for generation."""

    def __init__(self, message: str = "Designation data incomplete") -> None:
        super().__init__(message)


class GenerationContext:
    """Builds the context snapshot for document generation."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def build_context(
        self,
        template_id: UUID,
        case_file_id: UUID,
        user_variables: dict[str, str] | None = None,
    ) -> ContextSnapshot:
        """Build complete context snapshot."""
        template = await self._uow.templates.get_by_id(template_id)
        if not template:
            raise ContextBuildFailedError("Template not found")

        case_file = await self._uow.case_files.get_by_id(case_file_id)
        if not case_file:
            raise ContextBuildFailedError("Case file not found")

        employee = await self._uow.employees.get_by_id(case_file.employee_id)
        if not employee:
            raise ContextBuildFailedError("Employee not found")

        designation = None
        if case_file.case_type == "designacion":
            designation = await self._uow.designations.get_by_case_file_id(case_file_id)

        context: ContextSnapshot = {
            "template": {
                "id": str(template.id),
                "name": template.name,
                "document_type": template.document_type,
                "version": template.version,
                "body_template": template.body_template,
                "variables": template.variables,
            },
            "case_file": {
                "id": str(case_file.id),
                "case_number": case_file.case_number,
                "title": case_file.title,
                "description": case_file.description or "",
                "case_type": case_file.case_type,
                "status": case_file.status,
            },
            "employee": {
                "id": str(employee.id),
                "first_name": employee.first_name,
                "last_name": employee.last_name,
                "department": employee.department or "",
            },
            "designation": {
                "position_name": designation.position_name if designation else "",
                "organizational_unit": designation.organizational_unit
                if designation
                else "",
                "start_date": str(designation.start_date)
                if designation and designation.start_date
                else "",
                "legal_basis": designation.legal_basis if designation else "",
                "appointing_authority": designation.appointing_authority
                if designation
                else "",
                "salary_category": designation.salary_category if designation else "",
                "work_schedule": designation.work_schedule if designation else "",
                "observations": designation.observations if designation else "",
            },
            "variables": user_variables or {},
            "metadata": {
                "generated_at": datetime.now(UTC).isoformat(),
                "model": "",
                "attempt_id": "",
            },
        }

        metadata = context["metadata"]
        if isinstance(metadata, dict):
            metadata["context_hash"] = self.compute_hash(context)
        return context

    def validate_variables(
        self, template_variables: list[str], user_variables: dict[str, str]
    ) -> None:
        """Validate that all required variables are provided."""
        missing = [v for v in template_variables if v not in user_variables]
        if missing:
            raise MissingRequiredVariablesError(missing)

    @staticmethod
    def compute_hash(context_snapshot: ContextSnapshot) -> str:
        """Compute SHA-256 hash of context snapshot."""
        serialized = json.dumps(context_snapshot, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode()).hexdigest()
