"""Employee application service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from legal_ai.adapters.database.unit_of_work import UnitOfWork
from legal_ai.domain.employee import Employee
from legal_ai.domain.enums import DocumentType
from legal_ai.domain.normalization import (
    normalize_cuil,
    normalize_document_number,
    normalize_email,
    normalize_phone,
    normalize_text,
)


class EmployeeService:
    """Service handling employee business operations."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def create(
        self,
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
        """Create a new employee."""
        # Normalize inputs
        normalized_doc_number = normalize_document_number(
            document_type, document_number
        )
        normalized_first_name = normalize_text(first_name)
        normalized_last_name = normalize_text(last_name)
        normalized_email = normalize_email(email) if email else None
        normalized_phone = normalize_phone(phone) if phone else None
        normalized_position = position.strip() if position else None
        normalized_department = department.strip() if department else None
        normalized_cuil = normalize_cuil(cuil) if cuil else None

        # Check uniqueness
        existing = await self._uow.employees.get_by_employee_number(employee_number)
        if existing:
            raise EmployeeNumberConflictError(employee_number)

        existing_doc = await self._uow.employees.get_by_document(
            document_type, normalized_doc_number
        )
        if existing_doc:
            raise EmployeeDocumentConflictError("document_number", "document_number")

        if normalized_cuil:
            existing_cuil = await self._uow.employees.get_by_cuil(normalized_cuil)
            if existing_cuil:
                raise EmployeeDocumentConflictError("cuil", "cuil")

        # Create employee
        employee = Employee(
            id=uuid.uuid4(),
            employee_number=employee_number,
            first_name=normalized_first_name,
            last_name=normalized_last_name,
            document_type=document_type,
            document_number=normalized_doc_number,
            cuil=normalized_cuil,
            email=normalized_email,
            phone=normalized_phone,
            position=normalized_position,
            department=normalized_department,
            active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        return await self._uow.employees.create(employee)

    async def get_by_id(self, employee_id: uuid.UUID) -> Employee:
        """Get employee by ID."""
        employee = await self._uow.employees.get_by_id(employee_id)
        if employee is None:
            raise EmployeeNotFoundError(employee_id)
        return employee

    async def list(
        self,
        page: int = 1,
        page_size: int = 20,
        query: str | None = None,
        active: bool | None = None,
        department: str | None = None,
    ) -> tuple[list[Employee], int]:
        """List employees with pagination and filters."""
        return await self._uow.employees.list(
            page=page,
            page_size=page_size,
            query=query,
            active=active,
            department=department,
        )

    async def update(
        self,
        employee_id: uuid.UUID,
        first_name: str | None = None,
        last_name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        position: str | None = None,
        department: str | None = None,
    ) -> Employee:
        """Partial update of employee fields."""
        employee = await self._uow.employees.get_by_id(employee_id)
        if employee is None:
            raise EmployeeNotFoundError(employee_id)

        # Normalize inputs
        if first_name is not None:
            employee.first_name = normalize_text(first_name)
        if last_name is not None:
            employee.last_name = normalize_text(last_name)
        if email is not None:
            employee.email = normalize_email(email) if email else None
        if phone is not None:
            employee.phone = normalize_phone(phone) if phone else None
        if position is not None:
            employee.position = position.strip() if position else None
        if department is not None:
            employee.department = department.strip() if department else None

        employee.updated_at = datetime.now(UTC)
        return await self._uow.employees.update(employee)

    async def deactivate(self, employee_id: uuid.UUID) -> Employee | None:
        """Deactivate employee (idempotent)."""
        employee = await self._uow.employees.get_by_id(employee_id)
        if employee is None:
            raise EmployeeNotFoundError(employee_id)
        return await self._uow.employees.deactivate(employee_id)


# Domain exceptions


class EmployeeNotFoundError(Exception):
    """Raised when employee is not found."""

    def __init__(self, employee_id: uuid.UUID) -> None:
        self.employee_id = employee_id
        super().__init__(f"Employee {employee_id} not found")


class EmployeeNumberConflictError(Exception):
    """Raised when employee number already exists."""

    def __init__(self, employee_number: str) -> None:
        self.employee_number = employee_number
        super().__init__(f"Employee number {employee_number} already exists")


class EmployeeDocumentConflictError(Exception):
    """Raised when document number or CUIL already exists."""

    def __init__(self, field: str, conflict_type: str) -> None:
        self.field = field
        self.conflict_type = conflict_type
        super().__init__(f"Employee {conflict_type} conflict on {field}")
