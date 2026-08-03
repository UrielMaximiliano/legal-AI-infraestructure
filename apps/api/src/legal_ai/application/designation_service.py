"""Designation application service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.domain.designation_data import DesignationData
from legal_ai.domain.enums import CaseType


class CaseFileNotFoundError(Exception):
    """Case file not found."""

    def __init__(self, case_file_id: str) -> None:
        self.case_file_id = case_file_id
        super().__init__(f"Case file not found: {case_file_id}")


class CaseFileTypeIncompatibleError(Exception):
    """Case file type is not designacion."""

    def __init__(self, case_file_id: str) -> None:
        self.case_file_id = case_file_id
        super().__init__(f"Case file type incompatible: {case_file_id}")


class DesignationNotFoundError(Exception):
    """Designation data not found."""

    def __init__(self, case_file_id: str) -> None:
        self.case_file_id = case_file_id
        super().__init__(f"Designation not found for case file: {case_file_id}")


class DesignationExistsError(Exception):
    """Designation already exists for this case file."""

    def __init__(self, case_file_id: str) -> None:
        self.case_file_id = case_file_id
        super().__init__(f"Designation already exists: {case_file_id}")


class DesignationService:
    """Service handling designation data operations."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def create_designation(
        self,
        case_file_id: str,
        position_name: str,
        organizational_unit: str | None = None,
        start_date: str | None = None,
        legal_basis: str | None = None,
        appointing_authority: str | None = None,
        salary_category: str | None = None,
        work_schedule: str | None = None,
        observations: str | None = None,
    ) -> DesignationData:
        """Create designation data for a case file."""
        from datetime import date as date_type

        cf_id = uuid.UUID(case_file_id)
        case_file = await self._uow.case_files.get_by_id(cf_id)
        if not case_file:
            raise CaseFileNotFoundError(case_file_id)

        if case_file.case_type != CaseType.DESIGNACION:
            raise CaseFileTypeIncompatibleError(case_file_id)

        existing = await self._uow.designations.get_by_case_file_id(cf_id)
        if existing:
            raise DesignationExistsError(case_file_id)

        parsed_date = date_type.fromisoformat(start_date) if start_date else None

        designation = DesignationData(
            id=uuid.uuid4(),
            case_file_id=cf_id,
            position_name=position_name,
            organizational_unit=organizational_unit,
            start_date=parsed_date,
            legal_basis=legal_basis,
            appointing_authority=appointing_authority,
            salary_category=salary_category,
            work_schedule=work_schedule,
            observations=observations,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        return await self._uow.designations.create(designation)

    async def get_designation(self, case_file_id: str) -> DesignationData:
        """Get designation data for a case file."""
        cf_id = uuid.UUID(case_file_id)
        designation = await self._uow.designations.get_by_case_file_id(cf_id)
        if not designation:
            raise DesignationNotFoundError(case_file_id)
        return designation

    async def update_designation(
        self,
        case_file_id: str,
        position_name: str | None = None,
        organizational_unit: str | None = None,
        start_date: str | None = None,
        legal_basis: str | None = None,
        appointing_authority: str | None = None,
        salary_category: str | None = None,
        work_schedule: str | None = None,
        observations: str | None = None,
    ) -> DesignationData:
        """Update designation data."""
        from datetime import date as date_type

        cf_id = uuid.UUID(case_file_id)
        designation = await self._uow.designations.get_by_case_file_id(cf_id)
        if not designation:
            raise DesignationNotFoundError(case_file_id)

        if position_name is not None:
            designation.position_name = position_name
        if organizational_unit is not None:
            designation.organizational_unit = organizational_unit
        if start_date is not None:
            designation.start_date = date_type.fromisoformat(start_date)
        if legal_basis is not None:
            designation.legal_basis = legal_basis
        if appointing_authority is not None:
            designation.appointing_authority = appointing_authority
        if salary_category is not None:
            designation.salary_category = salary_category
        if work_schedule is not None:
            designation.work_schedule = work_schedule
        if observations is not None:
            designation.observations = observations

        designation.updated_at = datetime.now(UTC)
        return await self._uow.designations.update(designation)
